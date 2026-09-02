from pathlib import Path
import unittest

import social_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BilibiliVisibleResultsV11030Tests(unittest.TestCase):
    def test_bilibili_avif_derivative_is_restored_to_original_jpeg(self):
        transformed = (
            "https://i1.hdslb.com/bfs/archive/"
            "5d2109d27d87bcbf382817a98d8c2fbddec4ce2f.jpg"
            "@672w_378h_1c_!web-search-common-cover.avif"
        )
        original = (
            "https://i1.hdslb.com/bfs/archive/"
            "5d2109d27d87bcbf382817a98d8c2fbddec4ce2f.jpg"
        )
        self.assertEqual(
            social_browser._normalize_social_image_url(
                "bilibili", transformed
            ),
            original,
        )
        loader_source = (PROJECT_ROOT / "image_loader.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _normalize_bilibili_image_url", loader_source)
        self.assertIn(
            "value = _normalize_bilibili_image_url(value)", loader_source
        )

    def test_visible_result_cards_precede_navigation_text(self):
        result = social_browser._compose_social_visible_text(
            ["首页\n番剧\n底部版权"],
            [
                {
                    "visible_text": (
                        "【又一】看日出的可怜小黄毛 "
                        "作者 就打德就打德 6075"
                    )
                },
                {
                    "visible_text": (
                        "【又一充电中】第一次看日出 "
                        "作者 垒下浮云 94"
                    )
                },
            ],
        )
        lines = result.splitlines()
        self.assertTrue(lines[0].startswith("VISIBLE RESULT CARD:"))
        self.assertIn("又一充电中", result)
        self.assertLess(result.index("又一充电中"), result.index("首页"))

    def test_candidate_extractor_keeps_bilibili_result_after_page_chrome(self):
        class FakePage:
            def evaluate(self, script):
                self.script = script
                return [
                    {
                        "url": "https://search.bilibili.com/all?keyword=x",
                        "visible_text": "导航 " + str(index),
                        "image_url": "",
                        "image_alt": "",
                    }
                    for index in range(70)
                ] + [
                    {
                        "url": "https://www.bilibili.com/video/BV1visible",
                        "visible_text": "又一充电中 袁雨桢 相关视频",
                        "image_url": (
                            "//i2.hdslb.com/bfs/archive/cover.jpg"
                            "@672w_378h_1c_!web-search-common-cover.avif"
                        ),
                        "image_alt": "封面",
                    }
                ]

        page = FakePage()
        candidates = social_browser._extract_post_candidates(page, "bilibili")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["url"],
            "https://www.bilibili.com/video/BV1visible",
        )
        self.assertEqual(
            candidates[0]["image_url"],
            "https://i2.hdslb.com/bfs/archive/cover.jpg",
        )
        self.assertIn("inspected > 2000", page.script)
        self.assertIn("new Map()", page.script)
        self.assertIn('a[href*="/video/"]', page.script)

    def test_root_and_casper_social_browser_copies_match(self):
        root = (PROJECT_ROOT / "social_browser.py").read_text(encoding="utf-8")
        mirror = (PROJECT_ROOT / "casper/social_browser.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(root, mirror)


if __name__ == "__main__":
    unittest.main()
