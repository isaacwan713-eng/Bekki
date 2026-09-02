from pathlib import Path
import unittest
from unittest.mock import patch

import message_markdown
import social_browser
import tools


ROOT = Path(__file__).resolve().parents[1]


class _TextNode:
    def __init__(self, text=""):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class _TextList:
    def __init__(self, values):
        self.values = [_TextNode(value) for value in values]

    def count(self):
        return len(self.values)

    def nth(self, index):
        return self.values[index]


class _XiaohongshuDetailPage:
    def __init__(self):
        self.values = {
            "#detail-title": ["当前帖子标题"],
            "#detail-desc": ["当前作者正文，只讨论这一篇。"],
        }

    def locator(self, selector):
        return _TextList(self.values.get(selector, []))


class SocialEvidenceBindingV110413Tests(unittest.TestCase):
    def test_xiaohongshu_text_is_bounded_to_current_note(self):
        value = social_browser._bounded_xiaohongshu_post_text(
            _XiaohongshuDetailPage()
        )
        self.assertIn("CURRENT NOTE", value)
        self.assertIn("当前帖子标题", value)
        self.assertIn("当前作者正文", value)
        self.assertNotIn("相关推荐", value)

    def test_repeated_visual_ocr_tokens_are_collapsed(self):
        value = tools._collapse_repeated_social_tokens(
            "图鉴包含“杰妮”、“杰妮”、“杰妮”、“杰妮”，以及上海卡。",
            500,
        )
        self.assertEqual(value.count("杰妮"), 1)
        self.assertIn("重复项已省略", value)
        self.assertIn("上海卡", value)

    def test_default_mode_prefers_post_bound_frames_and_filters_unresolved(self):
        selected_title = "已定位帖子"
        unresolved_title = "仅搜索建议"
        evidence = {
            "page_summary": "搜索结果",
            "recent_post_count": 2,
            "selected_post_count": 2,
            "items": [
                {
                    "title": selected_title,
                    "author": "作者",
                    "resolved_date": "2026-09-01",
                    "engagement": "10",
                    "relevance_score": 95,
                },
                {
                    "title": unresolved_title,
                    "author": None,
                    "resolved_date": None,
                    "engagement": None,
                    "relevance_score": 90,
                },
            ],
            "excluded_count": 0,
            "warnings": [],
        }
        detail = {
            "platform": "xiaohongshu",
            "post_title": selected_title,
            "post_url": "https://www.rednote.com/explore/post123",
            "url": "https://www.rednote.com/explore/post123",
            "visible_text": "CURRENT NOTE: 当前正文",
            "search_visible_text": selected_title,
            "visual_frame": "post-frame",
            "visual_frames": ["post-frame"],
            "visual_assets": [{"kind": "media", "frame": "post-frame"}],
            "evidence_level": "opened_multimodal",
        }
        captured_titles = []

        def introductions(_message, recent_items, _details, _visual):
            captured_titles.extend(item["title"] for item in recent_items)
            return [
                {
                    "post_title": selected_title,
                    "introduction": "当前帖子摘要。",
                    "content_summary": "当前帖子摘要。",
                    "textual_findings": [],
                    "visual_findings": [],
                    "price_observations": [],
                    "answer_relevance": "相关。",
                    "uncertainty": "无。",
                    "evidence_level": "opened_multimodal",
                }
            ]

        with patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "测试",
                "selection_mode": "RELEVANCE",
                "recency_days": None,
                "ranking_mode": "DEFAULT",
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
                "visible_text": "搜索结果",
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
            tools, "extract_social_post_introductions", side_effect=introductions
        ), patch.object(
            tools, "synthesize_social_research_reply", return_value="完成"
        ):
            result = tools.social_research_controller(
                "去小红书查测试", ["xiaohongshu"]
            )

        visual_extract.assert_not_called()
        self.assertEqual(captured_titles, [selected_title])
        self.assertEqual(
            [item["post_title"] for item in result["social_post_summaries"]],
            [selected_title],
        )
        self.assertEqual(result["visual_evidence"]["frames_analyzed"], 0)

    def test_search_preview_card_labels_search_page_not_original_post(self):
        cards = tools.build_social_cards(
            [{"title": "预览帖子", "relevance_score": 90}],
            [
                {
                    "platform": "xiaohongshu",
                    "post_title": "预览帖子",
                    "url": "https://www.rednote.com/search_result?keyword=x",
                    "evidence_level": "search_only",
                }
            ],
            [],
            {"observations": []},
            selection_mode="RELEVANCE",
            include_unranked=True,
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["metadata"]["link_target"], "search")
        self.assertEqual(
            message_markdown.evidence_block(cards[0])["link"]["label"],
            "查看搜索页  ↗",
        )

    def test_concrete_post_keeps_original_post_label(self):
        card = {
            "type": "social_post",
            "title": "完整帖子",
            "summary": "正文",
            "url": "https://www.rednote.com/explore/post123",
            "metadata": {"link_target": "post"},
        }
        self.assertEqual(
            message_markdown.evidence_block(card)["link"]["label"],
            "打开原帖  ↗",
        )

    def test_runtime_mirrors_match(self):
        for relative in (
            "tools.py",
            "social_browser.py",
            "result_cards.py",
            "message_markdown.py",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
