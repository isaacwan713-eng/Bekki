import json
import base64
import sys
import types
import unittest
from unittest.mock import patch

import tools


def _recent(title="帖子 A", engagement="9"):
    return {
        "title": title,
        "author": "作者",
        "resolved_date": "2026-08-24",
        "engagement": engagement,
    }


def _detail(title="帖子 A", frame="frame-a"):
    return {
        "platform": "xiaohongshu",
        "post_title": title,
        "url": "https://www.rednote.com/explore/a",
        "image_url": "https://sns-img.example.com/a.jpg",
        "search_visible_text": title,
        "visible_text": title + " 正文内容",
        "visual_frame": frame,
    }


def _model_item(title="帖子 A", proof="心形点赞图标旁显示 128"):
    return {
        "post_title": title,
        "restaurant_name": None,
        "restaurant_name_evidence": None,
        "introduction": "帖子介绍正文内容。",
        "visual_description": "主图中可见两个联名玩具。",
        "evidence_quotes": ["正文内容"],
        "visible_features": ["两个联名玩具"],
        "suitability_note": "具体库存未知。",
        "uncertainty": "来自用户分享。",
        "engagement": {"likes": "128", "comments": None, "shares": None},
        "engagement_evidence": {"likes": proof, "comments": None, "shares": None},
    }


class SocialResearchV1394Tests(unittest.TestCase):
    def test_browser_captures_one_bounded_detail_frame(self):
        class FakePage:
            url = "https://www.rednote.com/explore/a"

            def goto(self, *_args, **_kwargs):
                return None

            def wait_for_timeout(self, _milliseconds):
                return None

            def locator(self, _selector):
                return types.SimpleNamespace(
                    inner_text=lambda timeout: "帖子 A 正文内容"
                )

            def screenshot(self, **kwargs):
                self.screenshot_kwargs = kwargs
                return b"detail-jpeg"

            def evaluate(self, _script):
                return []

            def close(self, **_kwargs):
                return None

        page = FakePage()
        context = types.SimpleNamespace(new_page=lambda: page)
        browser = types.SimpleNamespace(contexts=[context])
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
        sync_module.TimeoutError = TimeoutError
        package = types.ModuleType("playwright")
        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": sync_module},
        ):
            result = tools.social_browser.inspect_social_post_details(
                [
                    {
                        "platform": "xiaohongshu",
                        "url": page.url,
                        "post_title": "帖子 A",
                    }
                ]
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(base64.b64decode(result[0]["visual_frame"]), b"detail-jpeg")
        self.assertFalse(page.screenshot_kwargs["full_page"])

    def test_detail_frames_are_numbered_and_passed_to_visual_model(self):
        details = [
            _detail("帖子 A", "frame-a"),
            _detail("帖子 B", ""),
            _detail("帖子 C", "frame-c"),
        ]
        captured = []

        def model(_prompt_path, input_text, **kwargs):
            captured.append(
                {
                    "packet": json.loads(input_text),
                    "images": kwargs.get("images"),
                }
            )
            return {"items": []}

        with patch.object(tools, "run_ai_prompt", side_effect=model):
            tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent("帖子 A"), _recent("帖子 B"), _recent("帖子 C")],
                details,
                {"observations": []},
            )
        self.assertEqual(len(captured), 3)
        first_opened = captured[0]["packet"]["opened_post_details"]
        second_opened = captured[1]["packet"]["opened_post_details"]
        third_opened = captured[2]["packet"]["opened_post_details"]
        self.assertEqual(captured[0]["images"], ["frame-a"])
        self.assertIsNone(captured[1]["images"])
        self.assertEqual(captured[2]["images"], ["frame-c"])
        self.assertEqual(
            [item["visual_image_number"] for item in first_opened],
            [1],
        )
        self.assertIsNone(second_opened[0]["visual_image_number"])
        self.assertEqual(third_opened[0]["visual_image_number"], 1)

    def test_visually_bound_like_count_is_accepted(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"items": [_model_item()]},
        ):
            result = tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent()],
                [_detail()],
                {"observations": []},
            )
        self.assertEqual(result[0]["engagement"]["likes"], "128")
        self.assertEqual(
            result[0]["visual_description"], "主图中可见两个联名玩具。"
        )

    def test_collect_count_is_never_accepted_as_share(self):
        item = _model_item()
        item["engagement"] = {"likes": None, "comments": None, "shares": "9"}
        item["engagement_evidence"] = {
            "likes": None,
            "comments": None,
            "shares": "收藏星形图标旁显示 9",
        }
        with patch.object(
            tools, "run_ai_prompt", return_value={"items": [item]}
        ):
            result = tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent()],
                [_detail()],
                {"observations": []},
            )
        self.assertIsNone(result[0]["engagement"]["shares"])

    def test_visual_metric_without_count_in_proof_is_rejected(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"items": [_model_item(proof="可见心形点赞图标")]},
        ):
            result = tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent()],
                [_detail()],
                {"observations": []},
            )
        self.assertIsNone(result[0]["engagement"]["likes"])

    def test_visual_description_is_ignored_without_bound_frame(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            return_value={"items": [_model_item()]},
        ):
            result = tools.extract_social_post_introductions(
                "找麦当劳玩具",
                [_recent()],
                [_detail(frame="")],
                {"observations": []},
            )
        self.assertEqual(result[0]["visual_description"], "")
        self.assertIsNone(result[0]["engagement"]["likes"])

    def test_detail_visual_description_reaches_summary_and_card(self):
        intro = _model_item()
        summaries = tools.build_social_post_summaries([_recent()], [intro])
        cards = tools.build_social_cards(
            [_recent()], [_detail()], [intro], {"observations": []}
        )
        self.assertIn("图片可见：主图中可见两个联名玩具", summaries[0]["description"])
        self.assertIn("图片可见：主图中可见两个联名玩具", cards[0]["summary"])


if __name__ == "__main__":
    unittest.main()
