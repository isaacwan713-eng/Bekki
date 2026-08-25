import sys
import types
import unittest
from unittest.mock import patch

import social_browser


class FakeLocator:
    def __init__(self, page, card_data):
        self.page = page
        self.card_data = card_data
        self.first = self
        self.clicked = False

    def count(self):
        return 1

    def evaluate(self, _script):
        return dict(self.card_data)

    def click(self, timeout):
        self.clicked = True
        self.page.url = "https://www.rednote.com/explore/clicked-note"


class FakePage:
    def __init__(self, card_data):
        self.url = "https://www.rednote.com/search_result?keyword=Arcadia"
        self.locator = FakeLocator(self, card_data)
        self.restored_urls = []

    def bring_to_front(self):
        return None

    def get_by_text(self, _title, exact):
        return self.locator

    def wait_for_timeout(self, _milliseconds):
        return None

    def goto(self, url, **_kwargs):
        self.restored_urls.append(url)
        self.url = url


def fake_playwright_for(page):
    browser = types.SimpleNamespace(
        contexts=[types.SimpleNamespace(pages=[page])]
    )
    playwright = types.SimpleNamespace(
        chromium=types.SimpleNamespace(
            connect_over_cdp=lambda _url: browser
        )
    )

    class Context:
        def __enter__(self):
            return playwright

        def __exit__(self, *_args):
            return False

    module = types.ModuleType("playwright.sync_api")
    module.sync_playwright = lambda: Context()
    package = types.ModuleType("playwright")
    return package, module


class SocialResearchV1341Tests(unittest.TestCase):
    def test_exact_title_locates_real_post_link_and_image(self):
        page = FakePage(
            {
                "visible_text": "Arcadia这家新店会再去 2天前",
                "url": "https://www.rednote.com/explore/note-one",
                "image_url": "https://sns-img.example.com/noodles.jpg",
            }
        )
        package, module = fake_playwright_for(page)
        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": module},
        ), patch.object(social_browser, "cdp_is_ready", return_value=True):
            results = social_browser.resolve_social_post_targets(
                "xiaohongshu",
                ["Arcadia这家新店会再去"],
                expected_url=page.url,
            )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["url"].endswith("/explore/note-one"))
        self.assertIn("noodles.jpg", results[0]["image_url"])
        self.assertFalse(page.locator.clicked)

    def test_title_click_fallback_observes_post_url_then_restores_search(self):
        page = FakePage(
            {
                "visible_text": "Arcadia这家新店会再去 2天前",
                "url": "",
                "image_url": "https://sns-img.example.com/noodles.jpg",
            }
        )
        search_url = page.url
        package, module = fake_playwright_for(page)
        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": module},
        ), patch.object(social_browser, "cdp_is_ready", return_value=True):
            results = social_browser.resolve_social_post_targets(
                "xiaohongshu",
                ["Arcadia这家新店会再去"],
                expected_url=search_url,
            )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["opened_by_click"])
        self.assertTrue(results[0]["url"].endswith("/explore/clicked-note"))
        self.assertEqual(page.restored_urls, [search_url])

    def test_title_resolution_scans_multiple_virtualized_viewports(self):
        titles = [f"帖子 {index}" for index in range(5)]

        class ViewportLocator:
            def __init__(self, page, title):
                self.page = page
                self.title = title
                self.first = self

            def count(self):
                return int(self.page.position == titles.index(self.title))

            def evaluate(self, _script):
                index = titles.index(self.title)
                return {
                    "visible_text": self.title,
                    "url": f"https://www.rednote.com/explore/note-{index}",
                    "image_url": f"https://sns-img.example.com/note-{index}.jpg",
                }

        class ViewportPage:
            def __init__(self):
                self.url = "https://www.rednote.com/search_result?keyword=玩具"
                self.position = 4

            def bring_to_front(self):
                return None

            def get_by_text(self, title, exact):
                return ViewportLocator(self, title)

            def evaluate(self, script, *args):
                if "scrollTo(0, 0)" in script:
                    self.position = 0
                    return None
                if "scrollBy" in script:
                    before = self.position
                    self.position = min(self.position + 1, len(titles) - 1)
                    return {"before": before, "after": self.position}
                return 0

            def wait_for_timeout(self, _milliseconds):
                return None

        page = ViewportPage()
        package, module = fake_playwright_for(page)
        with patch.dict(
            sys.modules,
            {"playwright": package, "playwright.sync_api": module},
        ), patch.object(social_browser, "cdp_is_ready", return_value=True):
            results = social_browser.resolve_social_post_targets(
                "xiaohongshu", titles, expected_url=page.url
            )
        self.assertEqual([item["post_title"] for item in results], titles)
        self.assertEqual(len(results), 5)


if __name__ == "__main__":
    unittest.main()
