import json
from datetime import date
import unittest
from unittest.mock import patch

import tools


def _recent_item(index, engagement=None):
    return {
        "title": f"帖子 {index}",
        "author": f"作者 {index}",
        "time": "1天前",
        "resolved_date": "2026-08-23",
        "engagement": engagement,
        "kind": "opinion",
    }


def _detail(index):
    title = f"帖子 {index}"
    return {
        "platform": "xiaohongshu",
        "post_title": title,
        "url": f"https://www.rednote.com/explore/note-{index}",
        "image_url": f"https://sns-img.example.com/post-{index}.jpg",
        "search_visible_text": title,
        "visible_text": (
            f"{title} 正文介绍 {index} 点赞 {index}00 评论 {index}0 分享 {index}"
        ),
    }


def _introduction(index, likes=None, comments=None, shares=None):
    return {
        "post_title": f"帖子 {index}",
        "restaurant_name": None,
        "introduction": f"这是帖子 {index} 的简单介绍。",
        "visible_features": [],
        "suitability_note": "",
        "uncertainty": "来自用户分享。",
        "engagement": {
            "likes": likes,
            "comments": comments,
            "shares": shares,
        },
    }


class SocialResearchV139Tests(unittest.TestCase):
    def test_recent_social_evidence_keeps_at_most_seven_posts(self):
        raw = {
            "page_summary": "近期讨论",
            "recent_post_count": 8,
            "items": [
                {
                    "title": f"帖子 {index}",
                    "author": f"作者 {index}",
                    "time": "1天前",
                    "engagement": str(index),
                    "kind": "opinion",
                }
                for index in range(1, 9)
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            evidence = tools.extract_social_evidence(
                "visible social page",
                recency_days=7,
                current_date=date(2026, 8, 24),
            )
        self.assertEqual(evidence["recent_post_count"], 8)
        self.assertEqual(len(evidence["items"]), 7)

    def test_post_introductions_batch_seven_posts_into_three_calls(self):
        recent = [_recent_item(index) for index in range(1, 8)]
        details = [_detail(index) for index in range(1, 8)]

        def model_output(_prompt_path, input_text, **_kwargs):
            packet = json.loads(input_text)
            items = []
            for detail in packet["opened_post_details"]:
                title = detail["post_title"]
                index = int(title.split()[-1])
                items.append(
                    {
                        "post_title": title,
                        "restaurant_name": None,
                        "restaurant_name_evidence": None,
                        "introduction": f"正文介绍 {index}",
                        "evidence_quotes": [f"正文介绍 {index}"],
                        "visible_features": [],
                        "suitability_note": "",
                        "uncertainty": "",
                        "engagement": {
                            "likes": f"{index}00",
                            "comments": f"{index}0",
                            "shares": str(index),
                        },
                        "engagement_evidence": {
                            "likes": f"点赞 {index}00",
                            "comments": f"评论 {index}0",
                            "shares": f"分享 {index}",
                        },
                    }
                )
            return {"items": items}

        with patch.object(tools, "run_ai_prompt", side_effect=model_output) as model:
            introductions = tools.extract_social_post_introductions(
                "找推荐",
                recent,
                details,
                {"observations": []},
            )
        self.assertEqual(len(introductions), 7)
        self.assertEqual(model.call_count, 3)
        self.assertEqual(introductions[-1]["engagement"]["likes"], "700")

    def test_forged_metric_without_same_post_evidence_is_rejected(self):
        output = {
            "items": [
                {
                    "post_title": "帖子 1",
                    "restaurant_name": None,
                    "restaurant_name_evidence": None,
                    "introduction": "正文介绍 1",
                    "evidence_quotes": ["正文介绍 1"],
                    "visible_features": [],
                    "suitability_note": "",
                    "uncertainty": "",
                    "engagement": {
                        "likes": "9999",
                        "comments": None,
                        "shares": None,
                    },
                    "engagement_evidence": {
                        "likes": "点赞 9999",
                        "comments": None,
                        "shares": None,
                    },
                }
            ]
        }
        with patch.object(tools, "run_ai_prompt", return_value=output):
            introductions = tools.extract_social_post_introductions(
                "找推荐",
                [_recent_item(1)],
                [_detail(1)],
                {"observations": []},
            )
        self.assertIsNone(introductions[0]["engagement"]["likes"])

    def test_social_metric_parser_handles_common_visible_suffixes(self):
        self.assertEqual(tools._parse_social_metric("1.2万"), 12000)
        self.assertEqual(tools._parse_social_metric("2.5K"), 2500)
        self.assertEqual(tools._parse_social_metric("145"), 145)
        self.assertIsNone(tools._parse_social_metric("未知"))

    def test_cards_are_top_three_by_visible_engagement(self):
        recent = [_recent_item(index) for index in range(1, 6)]
        details = [_detail(index) for index in range(1, 6)]
        introductions = [
            _introduction(1, "100", "20", "5"),
            _introduction(2, "500", "20", "5"),
            _introduction(3, "300", "50", "5"),
            _introduction(4, "900", "20", "5"),
            _introduction(5, "200", "20", "5"),
        ]
        cards = tools.build_social_cards(
            recent, details, introductions, {"observations": []}
        )
        self.assertEqual(len(cards), 3)
        self.assertEqual(
            [card["title"] for card in cards],
            ["帖子 4", "帖子 2", "帖子 3"],
        )
        top_facts = cards[0]["sections"][0]["items"]
        self.assertEqual(top_facts["点赞"], "900")
        self.assertEqual(top_facts["评论"], "20")
        self.assertEqual(top_facts["转发/分享"], "5")

    def test_fewer_than_three_metric_posts_are_not_padded(self):
        recent = [_recent_item(index) for index in range(1, 5)]
        details = [_detail(index) for index in range(1, 5)]
        introductions = [
            _introduction(1, "100", None, None),
            _introduction(2, None, "20", None),
            _introduction(3, None, None, None),
            _introduction(4, None, None, None),
        ]
        cards = tools.build_social_cards(
            recent, details, introductions, {"observations": []}
        )
        self.assertEqual(len(cards), 2)
        self.assertEqual([card["title"] for card in cards], ["帖子 1", "帖子 2"])

    def test_summaries_describe_up_to_seven_posts(self):
        summaries = tools.build_social_post_summaries(
            [_recent_item(index) for index in range(1, 9)],
            [_introduction(index, str(index), None, None) for index in range(1, 8)],
        )
        self.assertEqual(len(summaries), 7)
        self.assertEqual(summaries[0]["description"], "这是帖子 7 的简单介绍。")
        self.assertEqual(summaries[-1]["post_title"], "帖子 1")

    def test_direct_reply_renders_every_summary_and_top_card_count(self):
        summaries = [
            {
                "post_title": f"帖子 {index}",
                "description": f"简单描述 {index}。",
                "author": f"作者 {index}",
                "published_at": "2026-08-24",
                "likes": str(index * 10),
                "comments": None,
                "shares": None,
                "search_visible_interaction": None,
            }
            for index in range(1, 6)
        ]
        reply = tools.render_social_research_reply(
            {"page_summary": "近期玩具讨论。"},
            summaries,
            [{"title": "A"}, {"title": "B"}, {"title": "C"}],
            7,
        )
        for index in range(1, 6):
            self.assertIn(f"{index}. 《帖子 {index}》", reply)
            self.assertIn(f"简单描述 {index}", reply)
        self.assertIn("最高的 3 条已经放在下方卡片中", reply)

    def test_generic_grid_interaction_is_not_rendered_as_likes(self):
        cards = tools.build_social_cards(
            [_recent_item(1, engagement="145")],
            [_detail(1)],
            [_introduction(1, None, None, None)],
            {"observations": []},
        )
        facts = cards[0]["sections"][0]["items"]
        self.assertEqual(facts["搜索页可见互动"], "145")
        self.assertNotIn("点赞", facts)


if __name__ == "__main__":
    unittest.main()
