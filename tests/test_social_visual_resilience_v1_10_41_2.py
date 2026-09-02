import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import result_cards
import social_browser
import tools


ROOT = Path(__file__).resolve().parents[1]


def _minimal_intro(title):
    return {
        "post_title": title,
        "primary_subject": "Karina",
        "primary_subject_evidence": title,
        "content_summary": "帖子展示 Karina 小卡及标价。",
        "textual_findings": [],
        "image_summary": "图片中有小卡。",
        "visual_findings": [],
        "price_observations": [],
        "answer_relevance": "与卡价查询相关。",
        "uncertainty": "币种未显示。",
    }


class _FreshCardPage:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def evaluate(self, script, title):
        self.calls.append((script, title))
        return self.value


class SocialVisualResilienceV110412Tests(unittest.TestCase):
    def test_optional_visual_model_failure_returns_empty_evidence(self):
        with patch.object(
            tools, "run_ai_prompt", side_effect=RuntimeError("CUDA unavailable")
        ):
            evidence = tools.extract_social_visual_evidence(
                ["frame"],
                "查小红书 Karina 小卡",
                [{"title": "30👝中文卡背"}],
                ["xiaohongshu"],
            )
        self.assertEqual(evidence["observations"], [])
        self.assertIn("继续读取帖子", evidence["warnings"][0])

    def test_price_shorthand_variants_are_grounded_without_currency(self):
        examples = {
            "30👝中文卡背": 30,
            "全图35🍞": 35,
            "小盘，均7/1": 7,
            "330💼出柚小卡盘": 330,
        }
        for source, expected in examples.items():
            with self.subTest(source=source):
                values = tools._clean_social_price_observations(
                    [], source, False
                )
                self.assertEqual(len(values), 1)
                self.assertEqual(values[0]["normalized_amount"], expected)
                self.assertTrue(values[0]["currency_unknown"])

    def test_xiaohongshu_price_title_still_builds_a_screenshot_card(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_root = Path(directory)
            screenshot = cache_root / "xiaohongshu_post.jpg"
            screenshot.write_bytes(b"test-jpeg")
            title = "30👝中文卡背"
            with patch.object(
                result_cards, "_social_media_cache_root", return_value=cache_root
            ):
                cards = tools.build_social_cards(
                    [
                        {
                            "title": title,
                            "author": "tikye",
                            "resolved_date": "2026-09-01",
                            "engagement": "Like",
                            "relevance_score": 90,
                        }
                    ],
                    [
                        {
                            "platform": "xiaohongshu",
                            "post_title": title,
                            "post_url": "https://www.rednote.com/explore/abc123",
                            "evidence_level": "search_only",
                            "visual_assets": [
                                {
                                    "kind": "search_preview",
                                    "label": "搜索结果预览",
                                    "local_path": str(screenshot),
                                }
                            ],
                        }
                    ],
                    [],
                    {"observations": []},
                    selection_mode="RECENT",
                    ranking_mode="PRICE",
                    include_unranked=False,
                )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], title)
        self.assertEqual(cards[0]["metadata"]["price"], "30👝（求售价；币种未注明）")
        self.assertEqual(cards[0]["images"][0]["label"], "搜索结果预览")
        self.assertEqual(cards[0]["url"], "https://www.rednote.com/explore/abc123")

    def test_price_mode_skips_search_page_visual_model_and_keeps_cards(self):
        title = "30👝中文卡背"
        evidence = {
            "page_summary": "近期卡价帖子",
            "recent_post_count": 1,
            "selected_post_count": 1,
            "items": [
                {
                    "title": title,
                    "author": "tikye",
                    "resolved_date": "2026-09-01",
                    "engagement": "Like",
                    "relevance_score": 90,
                }
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        detail = {
            "platform": "xiaohongshu",
            "post_title": title,
            "post_url": "https://www.rednote.com/explore/abc123",
            "url": "https://www.rednote.com/explore/abc123",
            "visible_text": title,
            "search_visible_text": title,
            "visual_assets": [
                {
                    "kind": "search_preview",
                    "label": "搜索结果预览",
                    "local_path": "/tmp/post.jpg",
                }
            ],
            "evidence_level": "search_only",
        }
        with patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "aespa Karina 小卡卡价 Top 10",
                "selection_mode": "RECENT",
                "recency_days": 30,
                "ranking_mode": "PRICE",
                "fallback_query": None,
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
                "visible_text": title,
                "visual_frames": ["overview-frame"],
                "post_candidates": [],
            },
        ), patch.object(
            tools, "extract_social_evidence", return_value=evidence
        ), patch.object(
            tools,
            "extract_social_visual_evidence",
            side_effect=AssertionError("overview vision must be skipped"),
        ) as visual_extract, patch.object(
            tools.social_browser,
            "resolve_social_post_targets",
            return_value=[detail],
        ), patch.object(
            tools.social_browser,
            "inspect_social_post_details",
            return_value=[detail],
        ), patch.object(
            tools.social_browser, "close_social_browser"
        ), patch.object(
            tools, "extract_social_post_introductions", return_value=[]
        ), patch.object(
            tools.result_cards, "clean_cards", side_effect=lambda cards: cards
        ):
            result = tools.social_research_controller(
                "去小红书查最近一个月 aespa Karina 小卡卡价 Top 10",
                ["xiaohongshu"],
            )
        visual_extract.assert_not_called()
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["metadata"]["price"], "30👝（求售价；币种未注明）")

    def test_price_intro_uses_compact_schema_with_ten_price_slots(self):
        captured = {}
        title = "卡价盘"

        def model(_prompt, _packet, **kwargs):
            captured.update(kwargs)
            return {"items": [_minimal_intro(title)]}

        with patch.object(tools, "run_ai_prompt", side_effect=model):
            output = tools.extract_social_post_introductions(
                "查 Karina 小卡卡价 Top 10",
                [{"title": title}],
                [
                    {
                        "platform": "xiaohongshu",
                        "post_title": title,
                        "visible_text": "卡价盘",
                        "search_visible_text": title,
                        "visual_frames": ["frame-1"],
                        "evidence_level": "opened_multimodal",
                    }
                ],
                {"observations": []},
            )
        properties = captured["json_schema"]["properties"]["items"][
            "items"
        ]["properties"]
        self.assertEqual(captured["num_ctx"], 8192)
        self.assertEqual(captured["num_predict"], 1500)
        self.assertEqual(properties["textual_findings"]["maxItems"], 1)
        self.assertEqual(properties["visual_findings"]["maxItems"], 2)
        self.assertEqual(properties["price_observations"]["maxItems"], 10)
        self.assertEqual(len(output), 1)

    def test_fresh_dom_card_reader_returns_live_card_data(self):
        expected = {
            "visible_text": "330💼出柚小卡盘 1小时前",
            "url": "https://www.rednote.com/explore/live123",
            "image_url": "https://sns-img.example.com/card.jpg",
            "clip": {"x": 1, "y": 2, "width": 300, "height": 420},
        }
        page = _FreshCardPage(expected)
        self.assertEqual(
            social_browser._fresh_social_title_card_data(
                page, "330💼出柚小卡盘"
            ),
            expected,
        )
        self.assertEqual(page.calls[0][1], "330💼出柚小卡盘")

    def test_karina_alias_includes_xiaohongshu_shorthand(self):
        groups = tools._verified_social_entity_aliases("aespa Karina 小卡卡价")
        self.assertEqual(
            tools._social_title_verified_alias("330💼出柚小卡盘", groups),
            "柚小卡",
        )

    def test_social_source_cards_require_a_concrete_post_url(self):
        self.assertFalse(
            result_cards.is_concrete_social_post_url(
                "https://www.rednote.com/search_result?keyword=karina"
            )
        )
        self.assertTrue(
            result_cards.is_concrete_social_post_url(
                "https://www.rednote.com/explore/abc123"
            )
        )
        self.assertFalse(
            result_cards.is_concrete_social_post_url(
                "https://example.com/rednote.com/explore/abc123"
            )
        )

    def test_runtime_mirrors_match(self):
        for relative in (
            "tools.py",
            "social_browser.py",
            "result_cards.py",
            "prompts/social_post_introduction.txt",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
