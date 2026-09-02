from unittest.mock import patch
import unittest

import social_browser
import tools


class SocialResearchV134Tests(unittest.TestCase):
    def test_visible_title_binds_post_url_and_image(self):
        matches = tools.match_social_post_candidates(
            [{"title": "Arcadia这家新店会再去｜10刀清汤牛肉面可以"}],
            [
                {
                    "platform": "xiaohongshu",
                    "url": "https://www.rednote.com/explore/abc",
                    "visible_text": "Arcadia这家新店会再去｜10刀清汤牛肉面可以 2天前",
                    "image_url": "https://sns-img.example.com/noodles.jpg",
                }
            ],
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["post_title"], "Arcadia这家新店会再去｜10刀清汤牛肉面可以")
        self.assertIn("noodles.jpg", matches[0]["image_url"])

    def test_introduction_rejects_unwritten_restaurant_name(self):
        model_output = {
            "items": [
                {
                    "post_title": "Arcadia清汤牛肉面",
                    "restaurant_name": "虚构牛肉面馆",
                    "restaurant_name_evidence": "这碗清汤牛肉面十刀",
                    "introduction": "帖子介绍了一碗十刀的清汤牛肉面。",
                    "evidence_quotes": ["这碗清汤牛肉面十刀"],
                    "visible_features": ["清汤牛肉面"],
                    "suitability_note": "没有看到儿童设施信息。",
                    "uncertainty": "餐厅名称未显示。",
                }
            ]
        }
        details = [
            {
                "post_title": "Arcadia清汤牛肉面",
                "visible_text": "这碗清汤牛肉面十刀，下次还会来。",
                "search_visible_text": "Arcadia清汤牛肉面",
            }
        ]
        with patch.object(tools, "run_ai_prompt", return_value=model_output):
            items = tools.extract_social_post_introductions(
                "找餐厅", [{"title": "Arcadia清汤牛肉面"}], details, {}
            )
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]["restaurant_name"])
        self.assertIn("十刀", items[0]["introduction"])

    def test_social_card_contains_real_image_and_grounded_intro(self):
        cards = tools.build_social_cards(
            [
                {
                    "title": "Arcadia清汤牛肉面",
                    "author": "Lulubagel",
                    "resolved_date": "2026-08-22",
                    "engagement": "145",
                }
            ],
            [
                {
                    "platform": "xiaohongshu",
                    "post_title": "Arcadia清汤牛肉面",
                    "url": "https://www.rednote.com/explore/abc",
                    "image_url": "https://sns-img.example.com/noodles.jpg",
                }
            ],
            [
                {
                    "post_title": "Arcadia清汤牛肉面",
                    "restaurant_name": None,
                    "introduction": "帖子介绍了一碗十刀的清汤牛肉面。",
                    "visible_features": ["帖子文字写明价格为十刀"],
                    "suitability_note": "未看到是否提供儿童座椅。",
                    "uncertainty": "餐厅名称未确认。",
                }
            ],
            {
                "observations": [
                    {
                        "post_title": "Arcadia清汤牛肉面",
                        "description": "画面中可见一碗面。",
                    }
                ]
            },
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "social_post")
        self.assertEqual(cards[0]["title"], "Arcadia清汤牛肉面")
        self.assertEqual(
            cards[0]["image"]["url"],
            "https://sns-img.example.com/noodles.jpg",
        )
        self.assertIn("十刀", cards[0]["summary"])
        self.assertIn("图片可见", cards[0]["summary"])

    def test_browser_candidate_extractor_rejects_non_post_links(self):
        class FakePage:
            def evaluate(self, _script):
                return [
                    {
                        "url": "https://www.rednote.com/search_result?keyword=x",
                        "visible_text": "搜索页",
                        "image_url": "https://sns-img.example.com/search.jpg",
                        "image_alt": "",
                    },
                    {
                        "url": "https://www.rednote.com/explore/abc",
                        "visible_text": "Arcadia清汤牛肉面 2天前",
                        "image_url": "https://sns-img.example.com/noodles.jpg",
                        "image_alt": "面",
                    },
                ]

        candidates = social_browser._extract_post_candidates(
            FakePage(), "xiaohongshu"
        )
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]["url"].endswith("/explore/abc"))

    def test_controller_returns_grounded_social_card_to_ui(self):
        recent = {
            "page_summary": "近期讨论",
            "recent_post_count": 1,
            "items": [
                {
                    "title": "Arcadia清汤牛肉面",
                    "author": "Lulubagel",
                    "resolved_date": "2026-08-22",
                    "engagement": "145",
                }
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        visual = {
            "observations": [
                {
                    "post_title": "Arcadia清汤牛肉面",
                    "description": "画面中可见一碗面。",
                }
            ]
        }
        candidate = {
            "platform": "xiaohongshu",
            "url": "https://www.rednote.com/explore/abc",
            "visible_text": "Arcadia清汤牛肉面 2天前",
            "image_url": "https://sns-img.example.com/noodles.jpg",
        }
        detail = {
            **candidate,
            "post_title": "Arcadia清汤牛肉面",
            "search_visible_text": candidate["visible_text"],
        }
        introductions = [
            {
                "post_title": "Arcadia清汤牛肉面",
                "restaurant_name": None,
                "introduction": "帖子介绍了一碗清汤牛肉面。",
                "visible_features": [],
                "suitability_note": "儿童设施未知。",
                "uncertainty": "餐厅名称未确认。",
            }
        ]
        with patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "Arcadia 牛肉面",
                "selection_mode": "RELEVANCE",
                "recency_days": None,
            },
        ), patch.object(tools.time, "sleep", return_value=None), patch.object(
            tools.social_browser,
            "open_social_search",
            return_value={"url": "https://www.rednote.com/search_result?keyword=x"},
        ), patch.object(
            tools.social_browser,
            "inspect_active_social_page",
            return_value={
                "url": "https://www.rednote.com/search_result?keyword=x",
                "visible_text": "Arcadia清汤牛肉面 2天前",
                "visual_frames": ["frame"],
                "post_candidates": [candidate],
            },
        ), patch.object(
            tools.social_browser, "inspect_social_post_details", return_value=[detail]
        ), patch.object(
            tools.social_browser, "close_social_browser"
        ), patch.object(
            tools, "extract_social_evidence", return_value=recent
        ), patch.object(
            tools, "extract_social_visual_evidence", return_value=visual
        ), patch.object(
            tools, "extract_social_post_introductions", return_value=introductions
        ):
            result = tools.social_research_controller(
                "去小红书找 Arcadia 餐厅", ["xiaohongshu"]
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["type"], "social_post")
        self.assertIsNotNone(result["cards"][0]["image"])
        self.assertIn("social_post_summaries", result)
        self.assertNotIn("1. 《Arcadia清汤牛肉面》", result["direct_reply"])
        self.assertEqual(result["cards"][0]["title"], "Arcadia清汤牛肉面")


if __name__ == "__main__":
    unittest.main()
