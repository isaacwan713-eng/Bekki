from pathlib import Path
import unittest

import social_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BilibiliCardFirstV11031Tests(unittest.TestCase):
    def test_direct_video_cards_replace_generic_profile_candidates(self):
        class FakeFrame:
            def evaluate(self, _script):
                return [
                    {
                        "url": "https://space.bilibili.com/1660392980",
                        "visible_text": "导航和账号入口",
                        "image_url": "",
                        "image_alt": "",
                        "source_kind": "generic_link",
                    },
                    {
                        "url": "https://www.bilibili.com/video/BV1first",
                        "visible_text": "【又一】袁雨桢相关视频 作者甲 6075",
                        "image_url": "https://i0.hdslb.com/cover.jpg",
                        "image_alt": "视频封面",
                        "source_kind": "result_card",
                    },
                    {
                        "url": "https://www.bilibili.com/video/BV1second",
                        "visible_text": "【又一充电中】直播回放 作者乙 94",
                        "image_url": "https://i0.hdslb.com/cover2.jpg",
                        "image_alt": "视频封面",
                        "source_kind": "result_card",
                    },
                ]

        class FakePage:
            frames = [FakeFrame()]

        candidates = social_browser._extract_post_candidates(
            FakePage(), "bilibili"
        )
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(
            item["source_kind"] == "result_card" for item in candidates
        ))
        self.assertTrue(all("/video/" in item["url"] for item in candidates))

    def test_candidates_are_collected_across_frames(self):
        class FakeFrame:
            def __init__(self, suffix):
                self.suffix = suffix

            def evaluate(self, _script):
                return [{
                    "url": (
                        "https://www.bilibili.com/video/BV1" + self.suffix
                    ),
                    "visible_text": "视频卡 " + self.suffix,
                    "image_url": "",
                    "image_alt": "",
                    "source_kind": "result_card",
                }]

        class FakePage:
            frames = [FakeFrame("main"), FakeFrame("child")]

        candidates = social_browser._extract_post_candidates(
            FakePage(), "bilibili"
        )
        self.assertEqual(
            {item["url"] for item in candidates},
            {
                "https://www.bilibili.com/video/BV1main",
                "https://www.bilibili.com/video/BV1child",
            },
        )

    def test_dom_diagnostics_sum_frame_counts(self):
        class FakeFrame:
            def __init__(self, values):
                self.values = values

            def evaluate(self, _script):
                return self.values

        class FakePage:
            frames = [
                FakeFrame({
                    "anchors": 800,
                    "video_links": 10,
                    "video_cards": 10,
                }),
                FakeFrame({
                    "anchors": 5,
                    "video_links": 2,
                    "video_cards": 2,
                }),
            ]

        self.assertEqual(
            social_browser._social_dom_diagnostics(FakePage()),
            {
                "frames": 2,
                "anchors": 805,
                "video_links": 12,
                "video_cards": 12,
            },
        )

    def test_root_and_casper_social_browser_copies_match(self):
        root = (PROJECT_ROOT / "social_browser.py").read_text(encoding="utf-8")
        mirror = (PROJECT_ROOT / "casper/social_browser.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(root, mirror)


if __name__ == "__main__":
    unittest.main()
