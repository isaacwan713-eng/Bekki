import unittest
from unittest.mock import patch

from casper import browser


class SearchFallbackBudgetTests(unittest.TestCase):
    def test_google_success_does_not_open_bing(self):
        def search(_query, count=7, engine="google"):
            if engine != "google":
                raise AssertionError("fallback should not run")
            return {
                "status": "OK",
                "results": [
                    {"url": f"https://example{i}.com/x", "domain": f"example{i}.com"}
                    for i in range(5)
                ],
            }

        with patch.object(browser, "search_web", side_effect=search) as model:
            result = browser.discover_web(
                "straw cup",
                count=5,
                multi_engine=True,
                engine_plan=("google", "bing"),
                country_code="US",
                minimum_results=4,
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(result["results"]), 5)

    def test_bing_runs_only_when_google_is_insufficient(self):
        def search(_query, count=7, engine="google"):
            if engine == "google":
                return {
                    "status": "OK",
                    "results": [{"url": "https://one.com/x", "domain": "one.com"}],
                }
            return {
                "status": "OK",
                "results": [
                    {"url": "https://two.com/x", "domain": "two.com"},
                    {"url": "https://three.com/x", "domain": "three.com"},
                ],
            }

        with patch.object(browser, "search_web", side_effect=search) as model:
            result = browser.discover_web(
                "straw cup",
                count=3,
                multi_engine=True,
                engine_plan=("google", "bing"),
                country_code="US",
                minimum_results=2,
            )
        self.assertEqual(model.call_count, 2)
        self.assertEqual(len(result["results"]), 3)


if __name__ == "__main__":
    unittest.main()
