import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import result_cards
import social_browser
import tools


def _model_item(title, quote="正文证据", price=None):
    return {
        "post_title": title,
        "primary_subject": None,
        "primary_subject_evidence": None,
        "content_summary": "读取了帖子正文。",
        "textual_findings": [
            {"finding": "正文包含可验证信息。", "evidence_quote": quote}
        ],
        "image_summary": "帖子图片证据。",
        "visual_findings": [
            {
                "finding": "图片中有可读标注。",
                "visible_basis": "可读标注",
                "confidence": "high",
            }
        ],
        "price_observations": [price] if price else [],
        "answer_relevance": "可用于回答。",
        "uncertainty": "币种未显示。" if price else "",
    }


class _Surface:
    def __init__(self, rows):
        self.rows = rows

    def evaluate(self, _script):
        return self.rows


class _Page:
    def __init__(self, rows):
        self.frames = [_Surface(rows)]


class SocialEvidencePackageV11039Tests(TestCase):
    def test_bilibili_footer_video_link_is_not_a_result_card(self):
        rows = [
            {
                "url": "https://www.bilibili.com/video/BV1Xx411c7cH/",
                "visible_text": "协议汇总 侵权申诉 帮助中心 社区中心 广告合作",
                "image_url": "",
                "source_kind": "result_card",
                "dom_card_matched": False,
            }
        ]
        self.assertEqual(
            social_browser._extract_post_candidates(_Page(rows), "bilibili"),
            [],
        )

    def test_bilibili_strict_dom_video_card_is_accepted(self):
        rows = [
            {
                "url": "https://www.bilibili.com/video/BV1Km66YvEDc/",
                "visible_text": "真实搜索结果 UP主 08-31",
                "image_url": "https://i0.hdslb.com/bfs/archive/cover.jpg",
                "source_kind": "result_card",
                "dom_card_matched": True,
            }
        ]
        result = social_browser._extract_post_candidates(_Page(rows), "bilibili")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_kind"], "result_card")

    def test_price_top_ten_overrides_model_popularity(self):
        model_plan = {
            "query": "aespa karina 小卡卡价",
            "selection_mode": "RECENT",
            "recency_days": 30,
            "ranking_mode": "POPULARITY",
            "fallback_query": None,
        }
        with patch.object(tools, "run_ai_prompt", return_value=model_plan):
            plan = tools.build_social_query_plan(
                "去小红书查最近一个月 aespa Karina 小卡卡价 Top 10",
                ["xiaohongshu"],
            )
        self.assertEqual(plan["ranking_mode"], "PRICE")

    def test_reddit_query_cannot_drop_the_problem_facet(self):
        model_plan = {
            "query": "home robot OR household robot r/robotics",
            "selection_mode": "RECENT",
            "recency_days": 30,
            "ranking_mode": "DISCUSSION",
            "fallback_query": None,
        }
        with patch.object(tools, "run_ai_prompt", return_value=model_plan):
            plan = tools.build_social_query_plan(
                "去 Reddit 的 r/robotics 搜索最近一个月讨论最多的家用机器人问题",
                ["reddit"],
            )
        self.assertIn("problems", plan["query"])
        self.assertTrue(plan["query"].endswith("r/robotics"))

    def test_marketplace_shorthand_is_an_unknown_currency_asking_price(self):
        values = tools._price_observations_from_text("330💼出柚小卡盘")
        self.assertEqual(values[0]["raw_amount"], "330")
        self.assertEqual(values[0]["normalized_amount"], 330)
        self.assertIsNone(values[0]["currency"])
        self.assertEqual(values[0]["price_type"], "asking")

    def test_xiaohongshu_card_keeps_three_images_and_body_capture(self):
        detail = {
            "platform": "xiaohongshu",
            "post_title": "卡价盘",
            "post_url": "https://www.rednote.com/explore/abc123",
            "url": "https://www.rednote.com/explore/abc123",
            "evidence_level": "opened_multimodal",
            "visual_assets": [
                {"kind": "media", "label": "图 1", "local_path": "/tmp/a.jpg"},
                {"kind": "media", "label": "图 2", "local_path": "/tmp/b.jpg"},
                {"kind": "media", "label": "图 3", "local_path": "/tmp/c.jpg"},
                {"kind": "text", "label": "正文", "local_path": "/tmp/d.jpg"},
            ],
        }
        recent = [{"title": "卡价盘", "relevance_score": 90}]
        intro = [{"post_title": "卡价盘", "introduction": "完整卡价图"}]
        with patch.object(tools.result_cards, "clean_cards", side_effect=lambda value: value):
            cards = tools.build_social_cards(
                recent, [detail], intro, {"observations": []},
                selection_mode="RELEVANCE", include_unranked=True,
            )
        self.assertEqual(
            [item["label"] for item in cards[0]["images"]],
            ["图 1", "图 2", "图 3", "正文"],
        )
        self.assertEqual(cards[0]["url"], detail["post_url"])

    def test_reddit_card_keeps_exactly_one_body_capture(self):
        detail = {
            "platform": "reddit",
            "post_title": "Home robot issues",
            "post_url": "https://www.reddit.com/r/robotics/comments/abc/post/",
            "url": "https://www.reddit.com/r/robotics/comments/abc/post/",
            "evidence_level": "opened_text",
            "visual_assets": [
                {"kind": "text", "label": "帖子正文", "local_path": "/tmp/a.jpg"},
                {"kind": "media", "label": "不应出现", "local_path": "/tmp/b.jpg"},
            ],
        }
        with patch.object(tools.result_cards, "clean_cards", side_effect=lambda value: value):
            cards = tools.build_social_cards(
                [{"title": detail["post_title"], "relevance_score": 90}],
                [detail],
                [{"post_title": detail["post_title"], "introduction": "问题讨论"}],
                {"observations": []},
                selection_mode="RECENT",
                include_unranked=True,
            )
        self.assertEqual(len(cards[0]["images"]), 1)
        self.assertEqual(cards[0]["images"][0]["label"], "帖子正文")

    def test_two_reddit_posts_share_one_text_only_model_call(self):
        calls = []

        def model(_prompt, packet, **kwargs):
            calls.append((json.loads(packet), kwargs.get("images")))
            opened = json.loads(packet)["opened_post_details"]
            return {"items": [_model_item(item["post_title"]) for item in opened]}

        details = [
            {
                "platform": "reddit",
                "post_title": title,
                "visible_text": "正文证据",
                "search_visible_text": title,
                "visual_frames": ["unused-image"],
                "evidence_level": "opened_text",
            }
            for title in ("帖子 A", "帖子 B")
        ]
        with patch.object(tools, "run_ai_prompt", side_effect=model):
            output = tools.extract_social_post_introductions(
                "总结问题",
                [{"title": "帖子 A"}, {"title": "帖子 B"}],
                details,
                {"observations": []},
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0][0]["opened_post_details"]), 2)
        self.assertIsNone(calls[0][1])
        self.assertEqual(len(output), 2)

    def test_xiaohongshu_four_assets_use_two_two_image_calls(self):
        calls = []

        def model(_prompt, packet, **kwargs):
            calls.append(kwargs.get("images"))
            price = None
            if kwargs.get("images") == ["frame-3", "frame-4"]:
                price = {
                    "raw_amount": "330",
                    "normalized_amount": 330,
                    "currency": None,
                    "price_type": "asking",
                    "item_binding": None,
                    "evidence_basis": "图片标注 330",
                    "confidence": "high",
                }
            return {"items": [_model_item("卡价盘", price=price)]}

        detail = {
            "platform": "xiaohongshu",
            "post_title": "卡价盘",
            "visible_text": "正文证据",
            "search_visible_text": "卡价盘",
            "visual_frames": ["frame-1", "frame-2", "frame-3", "frame-4"],
            "visual_assets": [
                {"label": "图 1"}, {"label": "图 2"},
                {"label": "图 3"}, {"label": "正文"},
            ],
            "evidence_level": "opened_multimodal",
        }
        with patch.object(tools, "run_ai_prompt", side_effect=model):
            output = tools.extract_social_post_introductions(
                "查看卡价", [{"title": "卡价盘"}], [detail],
                {"observations": []},
            )
        self.assertEqual(calls, [["frame-1", "frame-2"], ["frame-3", "frame-4"]])
        self.assertEqual(output[0]["price_observations"][0]["normalized_amount"], 330)

    def test_discussion_synthesis_leads_with_comment_order_and_sample_scope(self):
        summaries = [
            {
                "post_title": "A", "description": "问题 A", "comments": "41",
                "understanding_available": True, "evidence_level": "opened_text",
            },
            {
                "post_title": "B", "description": "问题 B", "comments": "17",
                "understanding_available": True, "evidence_level": "opened_text",
            },
        ]
        response = {
            "answer": "这些帖子讨论了功能局限。",
            "findings": [],
            "limitations": ["样本有限。"],
            "confidence": "low",
        }
        with patch.object(tools, "run_ai_prompt", return_value=response):
            reply = tools.synthesize_social_research_reply(
                "最近一个月讨论最多的问题", "home robot problems",
                {}, summaries, ["reddit"], "RECENT", "DISCUSSION",
            )
        self.assertTrue(reply.startswith("在这次可验证的 2 条帖子样本中"))
        self.assertLess(reply.index("41 条评论"), reply.index("17 条评论"))

    def test_gallery_cleaner_keeps_four_explicit_social_assets(self):
        source = Path(result_cards.__file__).read_text(encoding="utf-8")
        self.assertIn('image_limit = 4 if gallery_contract else 2', source)
        ui_source = Path(tools.__file__).with_name("ui.py").read_text(encoding="utf-8")
        self.assertIn('"打开原帖  ↗"', ui_source)
