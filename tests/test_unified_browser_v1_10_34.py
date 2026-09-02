import inspect
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import managed_browser
import social_browser
import tools
from casper import browser as casper_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UnifiedBrowserV11034Tests(unittest.TestCase):
    def setUp(self):
        managed_browser._browser_process = None
        managed_browser._announced_ready = False
        managed_browser._legacy_cleanup_done = False

    def test_all_browser_entry_points_share_one_new_session(self):
        self.assertEqual(managed_browser.CDP_PORT, 9225)
        self.assertEqual(social_browser.CDP_PORT, managed_browser.CDP_PORT)
        self.assertEqual(casper_browser.CDP_PORT, managed_browser.CDP_PORT)
        self.assertEqual(social_browser.CDP_URL, managed_browser.CDP_URL)
        self.assertEqual(casper_browser.CDP_URL, managed_browser.CDP_URL)
        expected_profile = Path("C:/Bekki/unified_browser_profile")
        with patch.object(
            managed_browser, "profile_dir", return_value=expected_profile
        ):
            self.assertEqual(
                social_browser.browser_profile_dir(), expected_profile
            )
            self.assertEqual(casper_browser._profile_dir(), expected_profile)

    def test_unified_browser_starts_normal_and_minimized(self):
        process = object()
        with patch.object(
            managed_browser, "cdp_is_ready", side_effect=(False, True)
        ), patch.object(
            managed_browser, "browser_mode", return_value="headed"
        ), patch.object(
            managed_browser, "edge_executable", return_value="C:/Edge/msedge.exe"
        ), patch.object(
            managed_browser,
            "profile_dir",
            return_value=Path("C:/Bekki/unified_browser_profile"),
        ), patch.object(
            managed_browser.subprocess, "Popen", return_value=process
        ) as opened:
            managed_browser.ensure_browser()

        command = opened.call_args.args[0]
        self.assertIn("--remote-debugging-port=9225", command)
        self.assertIn("--start-minimized", command)
        self.assertIn(
            "--user-data-dir=C:/Bekki/unified_browser_profile", command
        )
        self.assertFalse(any("headless" in item for item in command))
        self.assertIs(managed_browser._browser_process, process)

    def test_existing_normal_unified_browser_is_reused(self):
        with patch.object(
            managed_browser, "cdp_is_ready", return_value=True
        ), patch.object(
            managed_browser, "browser_mode", return_value="headed"
        ), patch.object(managed_browser.subprocess, "Popen") as opened:
            managed_browser.ensure_browser()
        opened.assert_not_called()

    def test_legacy_cleanup_targets_only_retired_bekki_sessions(self):
        source = inspect.getsource(managed_browser.close_legacy_managed_browsers)
        self.assertIn("--remote-debugging-port=9223", source)
        self.assertIn("--remote-debugging-port=9224", source)
        self.assertIn("social_browser_profile", source)
        self.assertIn("casper_browser_profile", source)
        self.assertNotIn("taskkill", source.casefold())

    def test_social_search_has_no_browser_replacement_path(self):
        source = inspect.getsource(social_browser.open_social_search)
        self.assertIn("ensure_social_browser()", source)
        self.assertIn("connect_over_cdp", source)
        self.assertNotIn("restart", source.casefold())
        self.assertNotIn("browser.close()", source)

    def test_social_cleanup_closes_only_social_tabs(self):
        class FakePage:
            def __init__(self, url):
                self.url = url
                self.closed = False

            def close(self, run_before_unload=False):
                del run_before_unload
                self.closed = True

        social_page = FakePage("https://www.bilibili.com/video/BV1Km66YvEDc")
        general_page = FakePage("https://www.google.com/search?q=bekki")

        class FakeContext:
            pages = [social_page, general_page]

        class FakeBrowser:
            contexts = [FakeContext()]

        class FakeChromium:
            def connect_over_cdp(self, url):
                self.url = url
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakePlaywrightContext:
            def __enter__(self):
                return FakePlaywright()

            def __exit__(self, *_args):
                return False

        playwright_package = types.ModuleType("playwright")
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.sync_playwright = lambda: FakePlaywrightContext()
        playwright_package.sync_api = sync_api
        with patch.object(
            social_browser, "cdp_is_ready", return_value=True
        ), patch.dict(
            sys.modules,
            {"playwright": playwright_package, "playwright.sync_api": sync_api},
        ):
            social_browser.close_social_browser()

        self.assertTrue(social_page.closed)
        self.assertFalse(general_page.closed)

    def test_generic_browser_fallback_uses_shared_cdp(self):
        source = inspect.getsource(tools.read_page_with_browser)
        self.assertIn("managed_browser.ensure_browser()", source)
        self.assertIn("managed_browser.CDP_URL", source)
        self.assertIn("connect_over_cdp", source)
        self.assertNotIn("chromium.launch", source)
        self.assertNotIn("browser.close()", source)

    def test_human_handoff_keeps_shared_browser_alive(self):
        source = inspect.getsource(casper_browser.open_human_handoff)
        self.assertIn("managed_browser.open_human_handoff", source)
        self.assertNotIn("_stop_casper_browser", source)

    def test_installer_validates_shared_browser_manager(self):
        installer = (PROJECT_ROOT / "INSTALL_STABLE_V1.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"managed_browser.py"', installer)
        self.assertIn('"unified_browser_profile"', installer)

    def test_root_and_casper_mirrors_match(self):
        for relative in ("social_browser.py", "tools.py"):
            root = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            mirror = (PROJECT_ROOT / "casper" / relative).read_text(
                encoding="utf-8"
            )
            self.assertEqual(root, mirror)


if __name__ == "__main__":
    unittest.main()
