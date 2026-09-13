from io import BytesIO
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

import social_browser
import tools
from casper import browser


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


def _cover_jpeg():
    image = Image.new("RGB", (640, 360), (24, 34, 55))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 610, 330), fill=(235, 188, 44))
    draw.ellipse((210, 75, 430, 295), fill=(37, 104, 214))
    destination = BytesIO()
    image.save(destination, format="JPEG", quality=86)
    return destination.getvalue()


class BilibiliDetailReadinessTests(unittest.TestCase):
    def test_video_identity_is_exact_and_query_independent(self):
        self.assertEqual(
            social_browser._bilibili_video_identity(
                "https://www.bilibili.com/video/BV1AbC234/?spm_id=x"
            ),
            "bv1abc234",
        )
        self.assertEqual(
            social_browser._bilibili_video_identity(
                "https://space.bilibili.com/1129115529"
            ),
            "",
        )

    def test_bound_detail_wait_receives_expected_video_identity(self):
        observed = {}

        class Page:
            def wait_for_function(self, script, identity, timeout):
                observed.update(
                    script=script, identity=identity, timeout=timeout
                )

        self.assertTrue(
            social_browser._wait_for_bilibili_video_detail(
                Page(),
                "https://www.bilibili.com/video/BV1AbC234/",
            )
        )
        self.assertEqual(observed["identity"], "bv1abc234")
        self.assertIn("currentIdentity !== expectedIdentity", observed["script"])
        self.assertLessEqual(observed["timeout"], 8000)

    def test_zero_visual_assets_get_one_bounded_retry(self):
        page = types.SimpleNamespace(
            url="https://www.bilibili.com/video/BV1safe123/",
            wait_for_timeout=Mock(),
        )
        with patch.object(
            social_browser,
            "_bilibili_cover_urls",
            side_effect=[[], ["https://i0.hdslb.com/bfs/archive/cover.jpg"]],
        ) as covers, patch.object(
            social_browser,
            "_download_post_image_jpeg",
            return_value=_cover_jpeg(),
        ), patch.object(
            social_browser,
            "_capture_bilibili_video_frame",
            side_effect=[b"", b""],
        ), patch.object(
            social_browser,
            "_wait_for_bilibili_video_detail",
            return_value=True,
        ) as waited:
            assets = social_browser._capture_social_post_assets(
                page, "bilibili"
            )
        self.assertEqual(covers.call_count, 2)
        waited.assert_called_once_with(page, page.url)
        self.assertEqual([item["kind"] for item in assets], ["video_cover"])


class NativeFactVisualBridgeTests(unittest.TestCase):
    @staticmethod
    def _candidate():
        return {
            "native_platform": "bilibili",
            "url": "https://www.bilibili.com/video/BV1safe123/",
            "title": "【四禧丸子】成员详细资料大公开",
            "native_visible_text": "官方视频 · 2022-01-15",
        }

    def test_native_reader_reopens_once_after_zero_bound_assets(self):
        first = {
            "url": self._candidate()["url"],
            "visible_text": "CURRENT VIDEO:\n标题: 【四禧丸子】成员详细资料大公开",
            "visual_frames": [],
            "visual_assets": [],
            "evidence_level": "opened_text",
        }
        second = {
            "url": self._candidate()["url"],
            "visible_text": (
                "CURRENT VIDEO:\n标题: 【四禧丸子】成员详细资料大公开\n"
                "简介: 沐霂、又一、梨安、恬豆"
            ),
            "visual_frames": ["ZmFrZS1ib3VuZC1mcmFtZQ=="],
            "visual_assets": [{"label": "视频帧 1"}],
            "evidence_level": "opened_multimodal",
        }
        with patch.object(
            social_browser,
            "inspect_social_post_details",
            side_effect=[[first], [second]],
        ) as inspected, patch.object(browser.time, "sleep", return_value=None):
            result = browser._read_native_fact_candidate(self._candidate())
        self.assertEqual(inspected.call_count, 2)
        self.assertTrue(result["success"])
        self.assertIn("沐霂", result["content"])
        self.assertEqual(result["page_images"], second["visual_frames"])
        self.assertEqual(result["page_image_labels"], ["视频帧 1"])

    def test_native_reader_does_not_retry_complete_multimodal_detail(self):
        detail = {
            "url": self._candidate()["url"],
            "visible_text": "CURRENT VIDEO:\n简介: 四名成员资料",
            "visual_frames": ["ZmFrZS1ib3VuZC1mcmFtZQ=="],
            "visual_assets": [{"label": "视频封面"}],
            "evidence_level": "opened_multimodal",
        }
        with patch.object(
            social_browser,
            "inspect_social_post_details",
            return_value=[detail],
        ) as inspected:
            result = browser._read_native_fact_candidate(self._candidate())
        inspected.assert_called_once()
        self.assertTrue(result["success"])

    def test_retry_keeps_richer_text_and_merges_later_bound_frame(self):
        rich_text = {
            "url": self._candidate()["url"],
            "visible_text": (
                "CURRENT VIDEO:\n标题: 成员详细资料\n"
                "简介: 沐霂、又一、梨安、恬豆；这是官方成员资料。"
            ),
            "visual_frames": [],
            "visual_assets": [],
            "evidence_level": "opened_text",
        }
        later_visual = {
            "url": self._candidate()["url"],
            "visible_text": "CURRENT VIDEO:\n标题: 成员详细资料",
            "visual_frames": ["ZmFrZS1ib3VuZC1mcmFtZQ=="],
            "visual_assets": [{"label": "视频封面"}],
            "evidence_level": "opened_multimodal",
        }
        with patch.object(
            social_browser,
            "inspect_social_post_details",
            side_effect=[[rich_text], [later_visual]],
        ), patch.object(browser.time, "sleep", return_value=None):
            result = browser._read_native_fact_candidate(self._candidate())
        self.assertIn("沐霂、又一、梨安、恬豆", result["content"])
        self.assertEqual(result["page_images"], later_visual["visual_frames"])

    def test_fact_extractor_receives_only_bound_source_images(self):
        source = {
            "title": "官方成员资料",
            "description": "官方视频",
            "url": "https://www.bilibili.com/video/BV1safe123/",
            "domain": "bilibili.com",
            "page_content": "CURRENT VIDEO:\n简介: 成员资料",
            "page_images": ["ZmFrZS1ib3VuZC1mcmFtZQ=="],
            "page_image_labels": ["视频帧 1"],
        }
        with patch.object(
            tools, "run_ai_prompt", return_value={"answer": "沐霂、又一、梨安、恬豆"}
        ) as model:
            answer = tools.extract_answers("2022年成员是谁？", [source])
        self.assertEqual(answer[0]["answer"], "沐霂、又一、梨安、恬豆")
        self.assertEqual(
            model.call_args.kwargs["images"],
            ["ZmFrZS1ib3VuZC1mcmFtZQ=="],
        )
        self.assertIn("Image 1=视频帧 1", model.call_args.args[1])

    def test_plain_web_extraction_keeps_visual_input_disabled(self):
        source = {
            "title": "普通网页",
            "description": "文本来源",
            "url": "https://example.com/fact",
            "domain": "example.com",
            "page_content": "明确文本事实",
        }
        with patch.object(
            tools, "run_ai_prompt", return_value={"answer": "明确文本事实"}
        ) as model:
            tools.extract_answers("事实是什么？", [source])
        self.assertIsNone(model.call_args.kwargs["images"])


class RecoveryContractTests(unittest.TestCase):
    def test_fact_prompt_keeps_single_frame_scope(self):
        prompt = (ROOT / "prompts" / "extract_single.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("one sampled frame is only one moment", prompt)
        self.assertIn("return null", prompt)

    def test_runtime_mirrors_match(self):
        self.assertEqual(
            (ROOT / "social_browser.py").read_bytes(),
            (ROOT / "casper" / "social_browser.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "tools.py").read_bytes(),
            (ROOT / "casper" / "tools.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "prompts" / "extract_single.txt").read_bytes(),
            (ROOT / "casper" / "prompts" / "extract_single.txt").read_bytes(),
        )

    def test_build_id(self):
        text = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('BEKKI_BUILD_ID = "' + BUILD_ID + '"', text)


if __name__ == "__main__":
    unittest.main()
