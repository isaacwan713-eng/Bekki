import base64
from datetime import date
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import social_browser
import tools


class SocialResearchV133Tests(unittest.TestCase):
    def test_social_query_preserves_user_language_without_platform_rewrite(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"query": "Arcadia 两岁小朋友 亲子餐厅"},
        ) as model:
            query = tools.build_social_query(
                "去小红书搜索 Arcadia 适合两岁小朋友的餐厅",
                ["xiaohongshu"],
            )
        self.assertEqual(query, "Arcadia 两岁小朋友 亲子餐厅")
        self.assertEqual(model.call_count, 1)
        for call in model.call_args_list:
            self.assertEqual(call.kwargs["model_name"], "gemma4:12b")
            self.assertIsNotNone(call.kwargs["json_schema"])
        prompt = (
            Path(__file__).resolve().parents[1]
            / "prompts" / "social_query.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("strict no-translation policy", prompt)
        self.assertIn("deadline 管理技巧", prompt)

    def test_strict_recency_filter_rejects_live_log_old_and_ambiguous_items(self):
        raw = {
            "page_summary": "小红书 recent social discussion",
            "recent_post_count": 0,
            "items": [
                {
                    "title": "五月的旧餐馆帖子",
                    "author": "A",
                    "time": "05-10",
                    "engagement": "129",
                    "kind": "discussion",
                },
                {
                    "title": "去年的陈村粉",
                    "author": "B",
                    "time": "2025-04-01",
                    "engagement": "665",
                    "kind": "discussion",
                },
                {
                    "title": "去年的韩料",
                    "author": "C",
                    "time": "2025-11-15",
                    "engagement": "211",
                    "kind": "discussion",
                },
                {
                    "title": "两天前的家常餐馆",
                    "author": "D",
                    "time": "2天前",
                    "engagement": "144",
                    "kind": "discussion",
                },
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
        self.assertEqual(evidence["recent_post_count"], 1)
        self.assertEqual(len(evidence["items"]), 1)
        self.assertEqual(evidence["items"][0]["title"], "两天前的家常餐馆")
        self.assertEqual(evidence["items"][0]["resolved_date"], "2026-08-22")
        self.assertEqual(evidence["excluded_count"], 3)

    def test_visual_evidence_is_bound_to_verified_recent_post_title(self):
        raw = {
            "frames_analyzed": 2,
            "visual_summary": "近期帖子图片展示餐桌和儿童高脚椅。",
            "observations": [
                {
                    "post_title": "两天前的家常餐馆",
                    "description": "图片可见餐桌旁有一把儿童高脚椅。",
                    "relevance": "这是与幼儿用餐相关的可见设施。",
                    "visible_text": [],
                    "confidence": "high",
                },
                {
                    "post_title": "未通过时间验证的旧帖子",
                    "description": "不应保留。",
                    "relevance": "",
                    "visible_text": [],
                    "confidence": "high",
                },
            ],
            "warnings": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw) as model:
            evidence = tools.extract_social_visual_evidence(
                ["frame-one", "frame-two"],
                "找适合两岁小朋友的餐厅",
                [{"title": "两天前的家常餐馆"}],
                ["xiaohongshu"],
            )
        self.assertEqual(evidence["frames_analyzed"], 2)
        self.assertEqual(len(evidence["observations"]), 1)
        self.assertEqual(
            evidence["observations"][0]["post_title"],
            "两天前的家常餐馆",
        )
        self.assertEqual(model.call_args.kwargs["images"], ["frame-one", "frame-two"])
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")
        self.assertGreaterEqual(model.call_args.kwargs["num_predict"], 1200)
        schema = model.call_args.kwargs["json_schema"]
        observations = schema["properties"]["observations"]
        self.assertEqual(observations["maxItems"], 3)
        visible_text = observations["items"]["properties"]["visible_text"]
        self.assertEqual(visible_text["maxItems"], 4)
        packet = json.loads(model.call_args.args[1])
        self.assertEqual(packet["required_narrative_language"], "Chinese")

    def test_social_prompts_require_chinese_narrative_and_bounded_ocr(self):
        visual_prompt = (tools.resource_path("prompts/social_visual_extract.txt"))
        intro_prompt = (tools.resource_path("prompts/social_post_introduction.txt"))
        with open(visual_prompt, "r", encoding="utf-8") as file:
            visual_text = file.read()
        with open(intro_prompt, "r", encoding="utf-8") as file:
            intro_text = file.read()
        self.assertIn("at most four distinct short strings", visual_text)
        self.assertIn("Never repeat the same OCR phrase", visual_text)
        self.assertIn("all narrative fields must be Chinese", visual_text)
        self.assertIn("must be Chinese", intro_text)
        self.assertIn("Preserve proper names", intro_text)

    def test_controller_merges_visible_text_and_bounded_visual_evidence(self):
        recent = {
            "page_summary": "近期讨论",
            "recent_post_count": 1,
            "items": [{"title": "两天前的家常餐馆"}],
            "excluded_count": 0,
            "warnings": [],
        }
        visual = {
            "frames_analyzed": 1,
            "visual_summary": "图片可见餐桌。",
            "observations": [],
            "warnings": [],
        }
        with patch.object(
            tools,
            "build_social_query_plan",
            return_value={
                "query": "Arcadia 亲子餐厅",
                "selection_mode": "RELEVANCE",
                "recency_days": None,
            },
        ), patch.object(
            tools.time, "sleep", return_value=None
        ), patch.object(
            tools.social_browser,
            "open_social_search",
            return_value={"url": "https://www.rednote.com/search_result?keyword=x"},
        ), patch.object(
            tools.social_browser,
            "inspect_active_social_page",
            return_value={
                "url": "https://www.rednote.com/search_result?keyword=x",
                "visible_text": "两天前的家常餐馆 2天前",
                "visual_frames": ["frame-one"],
            },
        ), patch.object(
            tools.social_browser, "close_social_browser"
        ) as close, patch.object(
            tools, "extract_social_evidence", return_value=recent
        ), patch.object(
            tools, "extract_social_visual_evidence", return_value=visual
        ) as visual_extract:
            result = tools.social_research_controller(
                "去小红书搜索 Arcadia 亲子餐厅",
                ["xiaohongshu"],
            )
        close.assert_called_once()
        visual_extract.assert_called_once_with(
            ["frame-one"],
            "去小红书搜索 Arcadia 亲子餐厅",
            recent["items"],
            ["xiaohongshu"],
        )
        self.assertEqual(result["visual_frame_count"], 1)
        self.assertIn("visual_evidence", result["context"])

    def test_browser_captures_three_bounded_visible_frames(self):
        class FakePage:
            url = "https://www.rednote.com/search_result?keyword=Arcadia"

            def bring_to_front(self):
                return None

            def locator(self, _selector):
                return types.SimpleNamespace(
                    inner_text=lambda timeout: "帖子标题\n2天前"
                )

            def screenshot(self, **_kwargs):
                return b"jpeg-bytes"

            def evaluate(self, _script):
                return None

            def wait_for_timeout(self, _milliseconds):
                return None

            def title(self):
                return "RedNote"

        page = FakePage()
        browser = types.SimpleNamespace(
            contexts=[types.SimpleNamespace(pages=[page])]
        )
        playwright = types.SimpleNamespace(
            chromium=types.SimpleNamespace(
                connect_over_cdp=lambda _url: browser
            )
        )

        class PlaywrightContext:
            def __enter__(self):
                return playwright

            def __exit__(self, *_args):
                return False

        sync_module = types.ModuleType("playwright.sync_api")
        sync_module.sync_playwright = lambda: PlaywrightContext()
        package = types.ModuleType("playwright")
        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": sync_module},
        ), patch.object(social_browser, "cdp_is_ready", return_value=True):
            result = social_browser.inspect_active_social_page(
                "xiaohongshu",
                expected_url=page.url,
            )
        self.assertEqual(len(result["visual_frames"]), 3)
        self.assertEqual(
            base64.b64decode(result["visual_frames"][0]), b"jpeg-bytes"
        )


if __name__ == "__main__":
    unittest.main()
