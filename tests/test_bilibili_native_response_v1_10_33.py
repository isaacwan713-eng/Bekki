import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

import managed_browser
import social_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BilibiliNativeResponseV11033Tests(unittest.TestCase):
    def tearDown(self):
        social_browser._BILIBILI_SEARCH_RESPONSE_CANDIDATES.clear()

    def test_nested_native_search_response_becomes_grounded_candidates(self):
        payload = {
            "code": 0,
            "data": {
                "result": [{
                    "result_type": "video",
                    "data": [{
                        "bvid": "BV1Km66YvEDc",
                        "title": (
                            "【<em class=\"keyword\">又一充电中</em>】"
                            "丸盒简史 袁雨桢"
                        ),
                        "author": "古原",
                        "pubdate": 1754006400,
                        "play": 6075,
                        "duration": "04:12",
                        "description": "又一与袁雨桢相关片段",
                        "pic": (
                            "//i0.hdslb.com/bfs/archive/cover.jpg"
                            "@672w_378h_1c_!web-search-common-cover.avif"
                        ),
                    }],
                }],
            },
        }
        candidates = (
            social_browser._extract_bilibili_search_response_candidates(
                payload
            )
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(
            candidate["url"],
            "https://www.bilibili.com/video/BV1Km66YvEDc",
        )
        self.assertNotIn("<em", candidate["visible_text"])
        self.assertIn("又一充电中", candidate["visible_text"])
        self.assertIn("袁雨桢", candidate["visible_text"])
        self.assertIn("UP主：古原", candidate["visible_text"])
        self.assertIn("播放：6075", candidate["visible_text"])
        self.assertEqual(
            candidate["image_url"],
            "https://i0.hdslb.com/bfs/archive/cover.jpg",
        )
        self.assertEqual(candidate["source_kind"], "network_result")

    def test_nonzero_native_response_fails_closed(self):
        self.assertEqual(
            social_browser._extract_bilibili_search_response_candidates(
                {"code": -352, "message": "risk control", "data": {}}
            ),
            [],
        )

    def test_only_bilibili_search_api_responses_are_accepted(self):
        self.assertTrue(
            social_browser._is_bilibili_search_api_response(
                "https://api.bilibili.com/x/web-interface/wbi/search/type"
            )
        )
        self.assertFalse(
            social_browser._is_bilibili_search_api_response(
                "https://api.bilibili.com/x/web-interface/view"
            )
        )
        self.assertFalse(
            social_browser._is_bilibili_search_api_response(
                "https://example.com/x/web-interface/wbi/search/type"
            )
        )

    def test_successful_page_response_is_cached_by_exact_query(self):
        class FakeResponse:
            url = (
                "https://api.bilibili.com/x/web-interface/"
                "wbi/search/type?search_type=video"
            )
            status = 200

            def json(self):
                return {
                    "code": 0,
                    "data": {"result": [{
                        "bvid": "BV1Km66YvEDc",
                        "title": "又一充电中 袁雨桢",
                        "pic": "//i0.hdslb.com/bfs/archive/cover.jpg",
                    }]},
                }

        key = social_browser._bilibili_search_cache_key(
            "https://search.bilibili.com/all?"
            "keyword=%E5%8F%88%E4%B8%80&order=totalrank"
        )
        social_browser._store_bilibili_search_response(key, FakeResponse())
        self.assertEqual(
            social_browser._BILIBILI_SEARCH_RESPONSE_CANDIDATES[key][0][
                "url"
            ],
            "https://www.bilibili.com/video/BV1Km66YvEDc",
        )

    def test_managed_browser_mode_reads_local_cdp_marker_only(self):
        class FakeReply:
            def raise_for_status(self):
                return None

            def json(self):
                return {"User-Agent": "HeadlessChrome/152.0.0.0"}

        with patch.object(
            managed_browser.requests, "get", return_value=FakeReply()
        ) as requested:
            self.assertEqual(
                social_browser._managed_social_browser_mode(), "headless"
            )
        requested.assert_called_once_with(
            managed_browser.CDP_URL + "/json/version", timeout=1.0
        )

    def test_response_listener_is_attached_before_navigation(self):
        source = inspect.getsource(social_browser.open_social_search)
        self.assertLess(source.index('page.on('), source.index("page.goto"))
        self.assertIn("ensure_social_browser()", source)
        self.assertNotIn("_restart_bilibili_browser_if_headless", source)

    def test_bilibili_does_not_replace_the_shared_browser(self):
        source = inspect.getsource(social_browser.open_social_search)
        self.assertNotIn("browser.close()", source)
        self.assertFalse(
            hasattr(social_browser, "_restart_bilibili_browser_if_headless")
        )

    def test_root_and_casper_social_browser_copies_match(self):
        root = (PROJECT_ROOT / "social_browser.py").read_text(encoding="utf-8")
        mirror = (PROJECT_ROOT / "casper/social_browser.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(root, mirror)


if __name__ == "__main__":
    unittest.main()
