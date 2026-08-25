import json
import sys
import types
import unittest
from unittest.mock import patch

import tools
from casper import browser


class RecommendationCountTests(unittest.TestCase):
    REGION = {
        "country_code": "US",
        "country_name": "United States",
        "preferred_search_engines": ["google", "bing"],
    }

    def _run_controller(self, request, model_results):
        plan = {
            "topic": "cup",
            "search_queries": ["best cup recommendations United States"],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": (
                "USER_EXPLICIT" if "三个" in request else "AI_DECIDES"
            ),
            "target_count": 3 if "三个" in request else 2,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ("google", "bing"),
            "reason": "AI recommendation plan",
        }
        discovery = {
            "status": "OK",
            "results": [
                {
                    "domain": "review-a.example",
                    "title": "Best cups",
                    "description": "Independent cup review.",
                    "url": "https://review-a.example/cups",
                },
                {
                    "domain": "review-b.example",
                    "title": "Tested cup picks",
                    "description": "Expert cup comparison.",
                    "url": "https://review-b.example/cups",
                },
                {
                    "domain": "review-c.example",
                    "title": "Cup recommendations",
                    "description": "Reviewed cup roundup.",
                    "url": "https://review-c.example/cups",
                },
                {
                    "domain": "shopping.yahoo.com",
                    "title": "Cup shopping results",
                    "description": "Shop online.",
                    "url": "https://shopping.yahoo.com/cups",
                },
            ],
        }
        pages = [
            {"success": True, "content": "Our best overall cup is YETI Rambler."},
            {"success": True, "content": "Duralex Picardie is our tested pick for cups."},
            {"success": True, "content": "Owala Tumbler is our top pick for cups."},
        ]
        fake_cards = types.SimpleNamespace(clean_cards=lambda values: values)
        fake_region = types.SimpleNamespace(
            detect_shopping_region=lambda: self.REGION
        )
        fake_location = types.SimpleNamespace(
            detect_location=lambda: self.REGION
        )

        def accept_verification(options, *_args, **_kwargs):
            verified = []
            for option in options:
                value = dict(option)
                value["verification_source_count"] = 1
                value["verification_source_domains"] = ["verify.example"]
                verified.append(value)
            return verified, []

        with patch.object(tools, "unload_model"), patch.object(
            browser, "_build_ai_recommendation_plan", return_value=plan
        ), patch.object(
            browser, "_search_engine_policy", return_value=("google", "bing")
        ), patch.object(
            browser, "discover_web", return_value=discovery
        ), patch.object(
            browser, "read_url", side_effect=pages
        ) as reader, patch.object(
            tools, "run_ai_prompt", side_effect=model_results
        ) as model, patch.dict(
            sys.modules,
            {
                "result_cards": fake_cards,
                "shopping_region": fake_region,
                "location": fake_location,
            },
        ), patch.object(
            browser,
            "_verify_ai_recommendation_options",
            side_effect=accept_verification,
        ), patch.object(
            browser,
            "_build_ai_verified_recommendation_reply",
            return_value=model_results[0]["reply"],
        ), patch.object(
            browser, "_discover_shopping_merchants"
        ) as merchant_discovery:
            result = browser.product_recommendation_controller(request)
        return result, model, reader, merchant_discovery

    def test_explicit_three_is_given_to_one_ai_synthesis_call(self):
        first = {
            "items": [
                {
                    "title": "YETI Rambler", "brand": "YETI",
                    "summary": "Independent best overall pick.",
                    "source_indexes": [1],
                    "verification_queries": ["YETI Rambler cup specifications"],
                },
                {
                    "title": "Duralex Picardie",
                    "brand": "Duralex",
                    "summary": "Independent tested pick.",
                    "source_indexes": [2],
                    "verification_queries": ["Duralex Picardie cup specifications"],
                },
                {
                    "title": "Owala Tumbler",
                    "brand": "Owala",
                    "summary": "Independent top pick.",
                    "source_indexes": [3],
                    "verification_queries": ["Owala Tumbler cup specifications"],
                },
            ],
            "reply": "这里是三个经过独立评测支持的杯子推荐。",
        }
        result, model, reader, merchant_discovery = self._run_controller(
            "给我推荐三个杯子", [first]
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual([card["title"] for card in result["cards"]], [
            "YETI Rambler", "Duralex Picardie", "Owala Tumbler"
        ])
        self.assertEqual(model.call_count, 1)
        first_packet = json.loads(model.call_args.args[1])
        self.assertEqual(first_packet["target_count"], 3)
        self.assertEqual(first_packet["count_policy"], "USER_EXPLICIT")
        self.assertEqual(result["direct_reply"], first["reply"])
        reader.assert_not_called()
        merchant_discovery.assert_not_called()

    def test_unspecified_count_is_ai_owned_and_does_not_force_retry(self):
        first = {
            "items": [
                {
                    "title": "YETI Rambler", "brand": "YETI",
                    "summary": "Independent best overall pick.",
                    "source_indexes": [1],
                    "verification_queries": ["YETI Rambler cup specifications"],
                }
            ],
            "reply": "我根据证据选择了这一款。",
        }
        result, model, _reader, _merchant_discovery = self._run_controller(
            "给我推荐一些杯子", [first]
        )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(model.call_count, 1)
        packet = json.loads(model.call_args.args[1])
        self.assertEqual(packet["target_count"], 2)
        self.assertEqual(packet["count_policy"], "AI_DECIDES")

    def test_shopping_subdomain_is_not_an_editorial_source(self):
        self.assertFalse(
            browser._is_independent_recommendation_source(
                {
                    "domain": "shopping.yahoo.com",
                    "title": "Cup shopping results",
                    "description": "Shop online",
                    "url": "https://shopping.yahoo.com/cups",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
