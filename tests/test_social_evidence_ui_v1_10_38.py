from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse
import inspect
import unittest
from unittest.mock import patch

import result_cards
import social_browser
import tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SocialEvidenceUiV11038Tests(unittest.TestCase):
    def test_reddit_discussion_search_uses_comments_and_month_window(self):
        parsed = urlparse(
            social_browser.social_search_url(
                "reddit",
                "home robot OR household robot r/robotics",
                selection_mode="RECENT",
                ranking_mode="DISCUSSION",
                recency_days=30,
            )
        )
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/r/robotics/search/")
        self.assertEqual(query["q"], ["home robot OR household robot"])
        self.assertEqual(query["restrict_sr"], ["1"])
        self.assertEqual(query["sort"], ["comments"])
        self.assertEqual(query["t"], ["month"])

    def test_chinese_discussion_intent_is_deterministic(self):
        self.assertEqual(
            tools._social_ranking_intent("最近一个月讨论最多的家用机器人问题"),
            "DISCUSSION",
        )
        self.assertEqual(
            tools._social_ranking_intent("找最热门的十条贴文"),
            "POPULARITY",
        )

    def test_reddit_votes_and_comments_are_parsed_separately(self):
        metrics = tools._social_metrics_for_post(
            {"engagement": "54 votes·12 comments"},
            {},
            ranking_mode="DISCUSSION",
        )
        self.assertEqual(metrics["display"]["likes"], "54")
        self.assertEqual(metrics["display"]["comments"], "12")
        self.assertEqual(metrics["numeric"]["likes"], 54)
        self.assertEqual(metrics["numeric"]["comments"], 12)
        self.assertEqual(metrics["rank_score"], 12)
        self.assertIsNone(metrics["search_visible_interaction"])

    def test_unknown_currency_price_values_are_kept_and_normalized(self):
        model_values = [
            {
                "raw_amount": "250",
                "normalized_amount": 250,
                "currency": None,
                "price_type": "displayed",
                "item_binding": None,
                "evidence_basis": "卡片右上角标注 250",
                "confidence": "high",
            },
            {
                "raw_amount": "1.9k",
                "normalized_amount": 1900,
                "currency": None,
                "price_type": "displayed",
                "item_binding": None,
                "evidence_basis": "卡片旁标注 1.9k",
                "confidence": "high",
            },
        ]
        cleaned = tools._clean_social_price_observations(
            model_values,
            "卡价图",
            has_images=True,
        )
        self.assertEqual(
            [item["normalized_amount"] for item in cleaned],
            [250, 1900],
        )
        self.assertTrue(all(item["currency_unknown"] for item in cleaned))

        bread = tools._price_observations_from_text("【已翻】15🍞纯柚10min")
        self.assertEqual(bread[0]["raw_amount"], "15🍞")
        self.assertEqual(bread[0]["normalized_amount"], 15)
        self.assertIsNone(bread[0]["currency"])

    def test_local_card_images_are_bounded_to_two_cache_files(self):
        with TemporaryDirectory() as temporary:
            cache = Path(temporary).resolve()
            paths = []
            for index in range(3):
                path = cache / f"evidence-{index}.jpg"
                path.write_bytes(b"jpeg-test")
                paths.append(str(path))
            card = {
                "type": "social_post",
                "title": "搜索页证据",
                "url": "https://www.rednote.com/search_result?keyword=test&type=51",
                "images": [
                    {"local_path": value, "alt": "证据图"}
                    for value in paths
                ],
            }
            with patch.object(
                result_cards,
                "_social_media_cache_root",
                return_value=cache,
            ):
                cleaned = result_cards.clean_card(card)
            self.assertEqual(len(cleaned["images"]), 2)
            self.assertEqual(cleaned["image"], cleaned["images"][0])
            self.assertEqual(
                [item["local_path"] for item in cleaned["images"]],
                paths[:2],
            )

    def test_search_only_card_keeps_price_and_discloses_weak_evidence(self):
        detail = {
            "platform": "xiaohongshu",
            "post_title": "烤鸭25刀",
            "url": "https://www.rednote.com/search_result?keyword=roast+duck&type=51",
            "evidence_level": "search_only",
            "local_image_paths": [],
        }
        recent = {
            "title": "烤鸭25刀",
            "author": "作者",
            "resolved_date": "2026-08-31",
            "engagement": None,
            "relevance_score": 90,
        }
        intro = {
            "post_title": "烤鸭25刀",
            "introduction": "搜索卡片显示烤鸭标价 25 美元。",
            "price_observations": [
                {
                    "raw_amount": "25刀",
                    "normalized_amount": 25,
                    "currency": "USD",
                    "currency_unknown": False,
                    "price_type": "displayed",
                    "item_binding": "烤鸭",
                    "evidence_basis": "烤鸭25刀",
                    "confidence": "high",
                }
            ],
        }
        cards = tools.build_social_cards(
            [recent],
            [detail],
            [intro],
            {"observations": []},
            selection_mode="RELEVANCE",
            include_unranked=True,
            max_cards=5,
        )
        self.assertEqual(len(cards), 1)
        facts = next(
            section["items"]
            for section in cards[0]["sections"]
            if section["kind"] == "facts"
        )
        warning = next(
            section["text"]
            for section in cards[0]["sections"]
            if section["kind"] == "warning"
        )
        self.assertEqual(facts["帖子标价"], "25刀")
        self.assertIn("搜索结果卡片", warning)
        self.assertNotIn("餐厅名称", facts)

    def test_aggregate_answer_is_downgraded_for_one_opened_post(self):
        summaries = [
            {
                "post_title": "One post",
                "description": "One grounded post.",
                "understanding_available": True,
                "evidence_level": "opened_text",
                "textual_findings": [],
                "visual_findings": [],
                "price_observations": [],
            }
        ]
        model_answer = {
            "answer": "目前只找到一个具体案例。",
            "findings": [
                {"post_title": "One post", "finding": "这是单一案例。"}
            ],
            "limitations": [],
            "confidence": "high",
        }
        with patch.object(tools, "run_ai_prompt", return_value=model_answer):
            reply = tools.synthesize_social_research_reply(
                "最近一个月讨论最多的问题",
                "problems",
                {},
                summaries,
                ["reddit"],
                "RECENT",
                ranking_mode="DISCUSSION",
            )
        self.assertIn("少于 3 条", reply)
        self.assertIn("不能据此代表整体讨论趋势", reply)

    def test_generic_or_login_pages_are_not_post_evidence(self):
        self.assertFalse(
            social_browser._detail_page_is_readable(
                "xiaohongshu",
                "https://www.rednote.com/",
                "About rednote Terms of Service Privacy Policy " * 5,
            )
        )
        self.assertFalse(
            social_browser._detail_page_is_readable(
                "reddit",
                "https://www.reddit.com/r/robotics/comments/abc/post/",
                "Continue with Google Continue with Apple Continue with Phone Number",
            )
        )
        source = inspect.getsource(social_browser._capture_post_visual_frames)
        self.assertIn("Known platforms deliberately omit it", source)

    def test_prompts_define_language_prices_and_evidence_levels(self):
        query = (PROJECT_ROOT / "prompts" / "social_query.txt").read_text(
            encoding="utf-8"
        )
        detail = (
            PROJECT_ROOT / "prompts" / "social_post_introduction.txt"
        ).read_text(encoding="utf-8")
        synthesis = (PROJECT_ROOT / "prompts" / "social_synthesis.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("platform-native", query)
        self.assertIn('"ranking_mode":"DISCUSSION"', query)
        self.assertIn("Unknown currency does not erase the price", detail)
        self.assertIn("`1.9k` -> 1900", detail)
        self.assertIn("search_only", synthesis)
        self.assertIn("needs at least three", synthesis)

    def test_root_and_casper_v38_mirrors_match(self):
        for relative in (
            "tools.py",
            "social_browser.py",
            "result_cards.py",
            "ui.py",
            "prompts/social_query.txt",
            "prompts/social_extract.txt",
            "prompts/social_post_introduction.txt",
            "prompts/social_synthesis.txt",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(
                    (PROJECT_ROOT / relative).read_bytes(),
                    (PROJECT_ROOT / "casper" / relative).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
