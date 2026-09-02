from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

import social_browser


ROOT = Path(__file__).resolve().parents[1]


def _jpeg(pattern):
    image = Image.new("RGB", (640, 360), (22, 28, 38))
    draw = ImageDraw.Draw(image)
    if pattern == "cover":
        draw.rectangle((40, 35, 600, 325), fill=(220, 205, 32))
        draw.ellipse((210, 80, 430, 300), fill=(30, 85, 210))
    elif pattern == "frame":
        draw.rectangle((20, 20, 620, 340), fill=(45, 170, 110))
        draw.polygon(((80, 310), (320, 35), (570, 310)), fill=(190, 45, 95))
    elif pattern == "black":
        draw.rectangle((302, 168, 338, 192), fill=(235, 235, 235))
    destination = BytesIO()
    image.save(destination, format="JPEG", quality=86)
    return destination.getvalue()


class _EmptyLocators:
    def count(self):
        return 0


class _MetadataPage:
    def evaluate(self, _script):
        return {
            "title": "当前视频标题",
            "description": "这里只是当前视频简介。",
            "author": "当前UP主",
            "cover": "https://i0.hdslb.com/bfs/archive/cover.jpg",
            "published_at": 1788278400,
            "bvid": "BV1current1234",
        }

    def locator(self, _selector):
        return _EmptyLocators()


class BilibiliVideoEvidenceV110414Tests(unittest.TestCase):
    def test_bilibili_text_is_bounded_to_current_video_metadata(self):
        value = social_browser._bounded_bilibili_video_text(
            _MetadataPage(), "搜索结果标题"
        )
        self.assertIn("CURRENT VIDEO", value)
        self.assertIn("当前视频标题", value)
        self.assertIn("当前UP主", value)
        self.assertIn("这里只是当前视频简介", value)
        self.assertNotIn("搜索结果标题", value)
        self.assertNotIn("相关视频", value)

    def test_black_loading_player_is_not_meaningful_evidence(self):
        self.assertFalse(social_browser._meaningful_raster_evidence(_jpeg("black")))
        self.assertTrue(social_browser._meaningful_raster_evidence(_jpeg("cover")))

    def test_bilibili_assets_are_cover_and_real_frame_only(self):
        cover = _jpeg("cover")
        frame = _jpeg("frame")
        with patch.object(
            social_browser,
            "_bilibili_cover_urls",
            return_value=["https://i0.hdslb.com/bfs/archive/cover.jpg"],
        ), patch.object(
            social_browser, "_download_post_image_jpeg", return_value=cover
        ), patch.object(
            social_browser, "_capture_bilibili_video_frame", return_value=frame
        ):
            assets = social_browser._capture_social_post_assets(
                object(),
                "bilibili",
                fallback_image_url="https://i0.hdslb.com/bfs/archive/fallback.jpg",
            )
        self.assertEqual(
            [asset["label"] for asset in assets],
            ["视频封面", "视频帧 1"],
        )
        self.assertNotIn("正文", [asset["label"] for asset in assets])

    def test_invalid_player_frame_leaves_one_useful_cover(self):
        cover = _jpeg("cover")
        with patch.object(
            social_browser,
            "_bilibili_cover_urls",
            return_value=["https://i0.hdslb.com/bfs/archive/cover.jpg"],
        ), patch.object(
            social_browser, "_download_post_image_jpeg", return_value=cover
        ), patch.object(
            social_browser, "_capture_bilibili_video_frame", return_value=b""
        ):
            assets = social_browser._capture_social_post_assets(
                object(), "bilibili"
            )
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["label"], "视频封面")

    def test_detail_capture_receives_search_result_cover_fallback(self):
        source = (ROOT / "social_browser.py").read_text(encoding="utf-8")
        self.assertIn(
            'fallback_image_url=target["search_image_url"]', source
        )
        self.assertIn(
            'if target["platform"] == "bilibili"', source
        )
        self.assertIn(
            'target["platform"] != "bilibili"', source
        )

    def test_prompt_does_not_treat_one_frame_as_a_video_summary(self):
        prompt = (ROOT / "prompts" / "social_post_introduction.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("视频封面", prompt)
        self.assertIn("not a transcript or a summary of the", prompt)

    def test_runtime_mirrors_match(self):
        self.assertEqual(
            (ROOT / "social_browser.py").read_bytes(),
            (ROOT / "casper" / "social_browser.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "prompts" / "social_post_introduction.txt").read_bytes(),
            (
                ROOT
                / "casper"
                / "prompts"
                / "social_post_introduction.txt"
            ).read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
