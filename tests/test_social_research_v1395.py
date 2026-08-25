from datetime import date
import unittest
from unittest.mock import patch

import tools


def _recent(title, engagement):
    return {
        "title": title,
        "author": "作者",
        "resolved_date": "2026-08-24",
        "engagement": engagement,
    }


def _intro(title, likes=None):
    return {
        "post_title": title,
        "restaurant_name": None,
        "introduction": title + " 的正文介绍。",
        "visual_description": "",
        "visible_features": [],
        "suitability_note": "",
        "uncertainty": "来自用户分享。",
        "engagement": {"likes": likes, "comments": None, "shares": None},
    }


class SocialResearchV1395Tests(unittest.TestCase):
    def test_recent_candidates_are_ranked_before_seven_item_cap(self):
        raw = {
            "page_summary": "近期讨论",
            "recent_post_count": 10,
            "items": [
                {
                    "title": f"帖子 {index}",
                    "author": f"作者 {index}",
                    "time": "1天前",
                    "engagement": str(index),
                    "kind": "discussion",
                }
                for index in range(1, 11)
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            evidence = tools.extract_social_evidence(
                "visible page",
                recency_days=7,
                current_date=date(2026, 8, 24),
            )
        self.assertEqual(evidence["recent_post_count"], 10)
        self.assertEqual(
            [item["title"] for item in evidence["items"]],
            [f"帖子 {index}" for index in range(10, 3, -1)],
        )

    def test_summaries_are_sorted_by_search_visible_interaction(self):
        recent = [
            _recent("低互动", "1"),
            _recent("高互动", "30"),
            _recent("中互动", "7"),
            _recent("未知互动", None),
        ]
        summaries = tools.build_social_post_summaries(recent, [])
        self.assertEqual(
            [item["post_title"] for item in summaries],
            ["高互动", "中互动", "低互动", "未知互动"],
        )

    def test_reply_explains_search_interaction_sort_once(self):
        summaries = tools.build_social_post_summaries(
            [_recent("帖子 A", "20"), _recent("帖子 B", "10")],
            [],
        )
        reply = tools.render_social_research_reply(
            {"page_summary": "近期讨论。"}, summaries, [{"title": "A"}], 7
        )
        sentence = (
            "以下按搜索页可见互动从多到少排列；该数值的具体类型未标注，"
            "不拆分为点赞、评论或分享。"
        )
        self.assertEqual(reply.count(sentence), 1)
        self.assertNotIn("（类型未标注）", reply)
        self.assertIn("搜索页可见互动 20", reply)

    def test_duplicate_model_items_are_kept_once(self):
        title = "全收集经验贴：麦当劳kitty x 哥斯拉"
        item = {
            "post_title": title,
            "restaurant_name": "麦当劳",
            "restaurant_name_evidence": "麦当劳",
            "introduction": "帖子分享麦当劳玩具收集经验。",
            "visual_description": "图片中可见多个玩具盒。",
            "evidence_quotes": ["麦当劳玩具收集经验"],
            "visible_features": ["多个玩具盒"],
            "suitability_note": "适合了解收集经验。",
            "uncertainty": "库存会变化。",
            "engagement": {"likes": None, "comments": None, "shares": None},
            "engagement_evidence": {
                "likes": None,
                "comments": None,
                "shares": None,
            },
        }
        detail = {
            "post_title": title,
            "search_visible_text": title,
            "visible_text": "麦当劳玩具收集经验",
            "visual_frame": "frame",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"items": [item, item, item]},
        ):
            introductions = tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent(title, "5")],
                [detail],
                {"observations": []},
            )
        self.assertEqual(len(introductions), 1)

    def test_cards_rank_by_search_visible_interaction_before_labeled_totals(self):
        recent = [_recent("帖子 A", "10"), _recent("帖子 B", "20")]
        details = [
            {
                "post_title": title,
                "platform": "xiaohongshu",
                "url": "https://www.rednote.com/explore/" + title[-1],
                "image_url": "",
            }
            for title in ("帖子 A", "帖子 B")
        ]
        cards = tools.build_social_cards(
            recent,
            details,
            [_intro("帖子 A", "1000"), _intro("帖子 B", "1")],
            {"observations": []},
        )
        self.assertEqual([card["title"] for card in cards], ["帖子 B", "帖子 A"])


if __name__ == "__main__":
    unittest.main()
