import sys
import types
from pathlib import Path
import unittest
from unittest.mock import patch

import managed_browser
import social_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEARCH_URL = (
    "https://search.bilibili.com/all?keyword=%E5%8F%88%E4%B8%80"
    "&order=totalrank"
)
CANDIDATE = {
    "platform": "bilibili",
    "url": "https://www.bilibili.com/video/BV1Km66YvEDc",
    "visible_text": "刷新后出现的 Bilibili 视频结果",
    "image_url": "",
    "source_kind": "result_card",
}


class _BodyLocator:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=0):
        del timeout
        if self.page.reload_count:
            return "刷新后可见的搜索结果页面"
        return "第一次加载的空白导航页面"


class _FakePage:
    def __init__(self):
        self.url = SEARCH_URL
        self.reload_count = 0
        self.response_listener_attached = False

    def bring_to_front(self):
        return None

    def on(self, event, callback):
        self.response_listener_attached = event == "response" and callable(callback)

    def wait_for_selector(self, *args, **kwargs):
        del args, kwargs
        return None

    def reload(self, **kwargs):
        del kwargs
        if not self.response_listener_attached:
            raise AssertionError("response listener must be attached before reload")
        self.reload_count += 1
        return None

    def wait_for_timeout(self, milliseconds):
        del milliseconds
        return None

    def locator(self, selector):
        if selector != "body":
            raise AssertionError("unexpected locator: " + selector)
        return _BodyLocator(self)

    def screenshot(self, **kwargs):
        del kwargs
        return b""

    def evaluate(self, script):
        del script
        return None

    def title(self):
        return "Bilibili search"


class _FakeBrowser:
    contexts = []


class _FakeChromium:
    def connect_over_cdp(self, url):
        self.url = url
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakePlaywrightContext:
    def __enter__(self):
        return _FakePlaywright()

    def __exit__(self, *_args):
        return False


def _playwright_modules():
    package = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakePlaywrightContext()
    sync_api.TimeoutError = type("FakePlaywrightTimeout", (Exception,), {})
    sync_api.Error = type("FakePlaywrightError", (Exception,), {})
    package.sync_api = sync_api
    return package, sync_api


class BilibiliFirstLoadRetryV11035Tests(unittest.TestCase):
    def setUp(self):
        social_browser._BILIBILI_SEARCH_RESPONSE_CANDIDATES.clear()

    def _inspect(self, page, extractor):
        package, sync_api = _playwright_modules()
        with patch.object(
            social_browser, "cdp_is_ready", return_value=True
        ), patch.object(
            social_browser, "_find_social_search_page", return_value=page
        ), patch.object(
            social_browser, "_extract_post_candidates", side_effect=extractor
        ), patch.object(
            social_browser,
            "_social_dom_diagnostics",
            return_value={
                "frames": 1,
                "anchors": 1,
                "video_links": 1,
                "video_cards": 1,
            },
        ), patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": sync_api},
        ):
            return social_browser.inspect_active_social_page(
                "bilibili", expected_url=SEARCH_URL
            )

    def test_empty_first_load_reloads_once_before_capture(self):
        page = _FakePage()

        def extractor(active_page, platform):
            self.assertEqual(platform, "bilibili")
            return [dict(CANDIDATE)] if active_page.reload_count else []

        result = self._inspect(page, extractor)

        self.assertEqual(page.reload_count, 1)
        self.assertTrue(page.response_listener_attached)
        self.assertEqual(result["post_candidates"], [CANDIDATE])
        self.assertIn("刷新后可见的搜索结果页面", result["visible_text"])
        self.assertNotIn("第一次加载的空白导航页面", result["visible_text"])

    def test_successful_first_load_is_not_reloaded(self):
        page = _FakePage()
        result = self._inspect(
            page,
            lambda active_page, platform: [dict(CANDIDATE)],
        )

        self.assertEqual(page.reload_count, 0)
        self.assertEqual(result["post_candidates"], [CANDIDATE])

    def test_native_response_candidate_also_prevents_reload(self):
        page = _FakePage()
        cache_key = social_browser._bilibili_search_cache_key(SEARCH_URL)
        network_candidate = {
            **CANDIDATE,
            "source_kind": "network_result",
        }
        social_browser._BILIBILI_SEARCH_RESPONSE_CANDIDATES[cache_key] = [
            network_candidate
        ]

        result = self._inspect(page, lambda active_page, platform: [])

        self.assertEqual(page.reload_count, 0)
        self.assertEqual(result["post_candidates"], [network_candidate])

    def test_second_empty_load_does_not_loop(self):
        page = _FakePage()
        result = self._inspect(page, lambda active_page, platform: [])

        self.assertEqual(page.reload_count, 1)
        self.assertEqual(result["post_candidates"], [])

    def test_new_edge_launch_suppresses_translation_prompt(self):
        source = (PROJECT_ROOT / "managed_browser.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--disable-translate"', source)
        self.assertIn("msEdgeTranslate", source)
        self.assertIn("TranslateUI", source)

    def test_root_and_casper_social_browser_match(self):
        self.assertEqual(
            (PROJECT_ROOT / "social_browser.py").read_bytes(),
            (PROJECT_ROOT / "casper" / "social_browser.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
