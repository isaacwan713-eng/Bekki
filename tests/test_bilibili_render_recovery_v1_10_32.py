import inspect
from pathlib import Path
import unittest

import social_browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BilibiliRenderRecoveryV11032Tests(unittest.TestCase):
    def test_connected_edge_version_becomes_non_headless_user_agent(self):
        user_agent = social_browser._modern_edge_user_agent("152.0.3300.12")
        self.assertIn("Chrome/152.0.3300.12", user_agent)
        self.assertIn("Edg/152.0.3300.12", user_agent)
        self.assertNotIn("HeadlessChrome", user_agent)

    def test_invalid_browser_version_is_not_faked(self):
        self.assertEqual(social_browser._modern_edge_user_agent("unknown"), "")
        self.assertEqual(social_browser._modern_edge_user_agent("99.0"), "")

    def test_bilibili_identity_is_applied_through_page_cdp_session(self):
        class FakeSession:
            def __init__(self):
                self.calls = []
                self.detached = False

            def send(self, method, payload):
                self.calls.append((method, payload))

            def detach(self):
                self.detached = True

        class FakeContext:
            def __init__(self):
                self.session = FakeSession()

            def new_cdp_session(self, _page):
                return self.session

        class FakeBrowser:
            version = "152.0.3300.12"

        context = FakeContext()
        self.assertTrue(
            social_browser._apply_bilibili_browser_identity(
                FakeBrowser(), context, object()
            )
        )
        method, payload = context.session.calls[0]
        self.assertEqual(method, "Network.setUserAgentOverride")
        self.assertNotIn("HeadlessChrome", payload["userAgent"])
        self.assertEqual(payload["platform"], "Windows")
        self.assertTrue(payload["acceptLanguage"].startswith("zh-CN"))
        self.assertTrue(context.session.detached)

    def test_browser_identity_is_applied_before_bilibili_navigation(self):
        source = inspect.getsource(social_browser.open_social_search)
        self.assertLess(
            source.index("_apply_bilibili_browser_identity"),
            source.index("page.goto"),
        )

    def test_legacy_footer_video_link_is_not_search_evidence(self):
        class FakePage:
            def evaluate(self, _script):
                return [{
                    "url": "https://www.bilibili.com/video/BV1Xx411c7cH/",
                    "visible_text": "协议汇总 活动中心 侵权申诉 帮助中心 社区中心",
                    "image_url": "",
                    "image_alt": "",
                    "source_kind": "generic_link",
                }]

        self.assertEqual(
            social_browser._extract_post_candidates(FakePage(), "bilibili"),
            [],
        )

    def test_large_site_chrome_with_logo_is_not_a_legacy_card(self):
        class FakePage:
            def evaluate(self, _script):
                return [{
                    "url": "https://www.bilibili.com/video/BV1Xx411c7cH/",
                    "visible_text": "页面导航 " * 160,
                    "image_url": "https://i0.hdslb.com/bfs/static/logo.png",
                    "image_alt": "bilibili",
                    "source_kind": "generic_link",
                }]

        self.assertEqual(
            social_browser._extract_post_candidates(FakePage(), "bilibili"),
            [],
        )

    def test_candidate_scan_includes_open_shadow_roots(self):
        class FakePage:
            def __init__(self):
                self.script = ""

            def evaluate(self, script):
                self.script = script
                return []

        page = FakePage()
        social_browser._extract_post_candidates(page, "bilibili")
        self.assertIn("node.shadowRoot", page.script)
        self.assertIn("const queryAll", page.script)
        self.assertIn("inferredCard", page.script)

    def test_root_and_casper_social_browser_copies_match(self):
        root = (PROJECT_ROOT / "social_browser.py").read_text(encoding="utf-8")
        mirror = (PROJECT_ROOT / "casper/social_browser.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(root, mirror)


if __name__ == "__main__":
    unittest.main()
