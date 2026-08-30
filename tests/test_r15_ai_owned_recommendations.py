import json
import sys
import types
import unittest
from unittest.mock import patch

import tools
from casper import browser


class AIOwnedRecommendationTests(unittest.TestCase):
    REGION = {
        "country_code": "US",
        "country_name": "United States",
        "preferred_search_engines": ["google", "bing"],
    }

    def test_ai_plan_owns_topic_features_count_queries_and_engines(self):
        raw = {
            "topic": "straw cup",
            "search_queries": [
                "best straw cups expert reviews 2026 United States"
            ],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 2,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ["google", "bing"],
            "reason": "The user asked for a few straw-cup recommendations.",
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw) as model:
            plan = browser._build_ai_recommendation_plan(
                "给我推荐几个吸管杯", "", self.REGION
            )
        self.assertEqual(plan["topic"], "straw cup")
        self.assertEqual(plan["criteria"], [])
        self.assertEqual(plan["audience_scope"], "GENERAL_UNSPECIFIED")
        self.assertEqual(plan["count_policy"], "AI_DECIDES")
        self.assertEqual(plan["target_count"], 2)
        self.assertEqual(plan["engines"], ("google", "bing"))
        self.assertEqual(model.call_count, 1)
        packet = json.loads(model.call_args.args[1])
        self.assertEqual(packet["current_user_request"], "给我推荐几个吸管杯")
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")

    def test_ai_reason_reconciles_explicit_adult_scope_without_an_extra_call(self):
        raw = {
            "topic": "tumbler with straw",
            "search_queries": ["best tumblers with straws expert reviews"],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general adult everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 3,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ["google", "bing"],
            "reason": "The user requested tumblers with straws for adult use.",
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw) as model:
            plan = browser._build_ai_recommendation_plan(
                "推荐几个成人用的吸管杯", "", self.REGION
            )
        self.assertEqual(plan["audience_scope"], "EXPLICIT")
        self.assertEqual(model.call_count, 1)

    def test_controller_never_calls_shopping_planner_or_python_category_gate(self):
        plan = {
            "topic": "straw cup",
            "search_queries": [
                "best straw cups expert reviews 2026 United States"
            ],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 2,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ("google", "bing"),
            "reason": "AI plan",
        }
        sources = [
            {
                "index": 1,
                "domain": "review-a.example",
                "title": "Independent drinkware guide",
                "description": "Editorial testing and recommendations.",
                "url": "https://review-a.example/guide",
            },
            {
                "index": 2,
                "domain": "review-b.example",
                "title": "Family drinkware comparison",
                "description": "Expert comparison.",
                "url": "https://review-b.example/guide",
            },
        ]
        ai_result = {
            "items": [
                {
                    "title": "Option Alpha",
                    "brand": "Alpha",
                    "summary": "AI judged it the strongest all-around choice.",
                    "source_indexes": [1],
                    "verification_queries": ["Option Alpha straw cup specs"],
                },
                {
                    "title": "Option Beta",
                    "brand": "Beta",
                    "summary": "AI judged it useful for a different preference.",
                    "source_indexes": [2],
                    "verification_queries": ["Option Beta straw cup specs"],
                },
            ],
            "reply": "我根据独立评测选择了两款吸管杯。",
        }
        candidate_options, _ = browser._accept_ai_recommendation_options(
            ai_result, sources
        )
        verified_options = []
        for option in candidate_options:
            verified = dict(option)
            verified["verification_source_count"] = 1
            verified["verification_source_domains"] = ["verify.example"]
            verified_options.append(verified)
        fake_cards = types.SimpleNamespace(clean_cards=lambda values: values)
        fake_region = types.SimpleNamespace(
            detect_shopping_region=lambda: self.REGION
        )
        fake_location = types.SimpleNamespace(
            detect_location=lambda: self.REGION
        )
        with patch.object(
            browser, "_build_ai_recommendation_plan", return_value=plan
        ), patch.object(
            browser,
            "_collect_recommendation_sources",
            return_value=(sources, "OK"),
        ) as collect, patch.object(
            browser, "_enrich_recommendation_sources", return_value=sources
        ), patch.object(
            browser,
            "_ask_ai_for_recommendation_options",
            return_value=(candidate_options, ai_result["reply"]),
        ) as candidate_ai, patch.object(
            browser,
            "_verify_ai_recommendation_options",
            return_value=(verified_options, []),
        ) as verify_ai, patch.object(
            browser,
            "_build_ai_verified_recommendation_reply",
            return_value=ai_result["reply"],
        ), patch.object(
            tools, "unload_model"
        ) as unload, patch.object(
            tools, "build_shopping_plan"
        ) as shopping_plan, patch.object(
            browser, "_source_mentions_product_query"
        ) as category_gate, patch.object(
            browser, "_discover_shopping_merchants"
        ) as merchants, patch.dict(
            sys.modules,
            {
                "result_cards": fake_cards,
                "shopping_region": fake_region,
                "location": fake_location,
            },
        ):
            result = browser.product_recommendation_controller(
                "给我推荐几个吸管杯"
            )
        shopping_plan.assert_not_called()
        category_gate.assert_not_called()
        merchants.assert_not_called()
        self.assertEqual(collect.call_args.args[0], plan["search_queries"])
        self.assertEqual(collect.call_args.args[2], plan["engines"])
        candidate_ai.assert_called_once()
        verify_ai.assert_called_once()
        self.assertEqual(len(result["cards"]), 2)
        self.assertEqual(result["direct_reply"], ai_result["reply"])
        self.assertEqual(result["requirements"], [])
        self.assertEqual(
            [call.args[0] for call in unload.call_args_list],
            ["gemma4:12b", "llama3.2:latest", "gemma4:12b"],
        )

    def test_python_binding_does_not_semantically_rejudge_ai_choice(self):
        sources = [
            {
                "index": 1,
                "domain": "review.example",
                "title": "Opaque editorial title",
                "description": "Opaque editorial description",
                "url": "https://review.example/article",
            }
        ]
        raw = {
            "items": [
                {
                    "title": "AI Selected Product",
                    "brand": "AI Brand",
                    "summary": "The AI judged the supplied evidence relevant.",
                    "source_indexes": [1],
                    "verification_queries": ["AI Selected Product specs"],
                }
            ],
            "reply": "AI-owned final recommendation.",
        }
        options, reply = browser._accept_ai_recommendation_options(raw, sources)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["title"], "AI Selected Product")
        self.assertEqual(reply, raw["reply"])

    def test_shopping_path_remains_separate_and_strict(self):
        source = tools.resource_path("casper/browser.py")
        with open(source, "r", encoding="utf-8") as file:
            text = file.read()
        recommendation_body = text.split(
            "def product_recommendation_controller", 1
        )[1].split("def _verified_brand_evidence", 1)[0]
        shopping_body = text.split(
            "def shopping_research_controller", 1
        )[1]
        self.assertNotIn("build_shopping_plan(", recommendation_body)
        self.assertIn("build_shopping_plan(", shopping_body)
        self.assertIn("_build_ai_recommendation_plan(", recommendation_body)


if __name__ == "__main__":
    unittest.main()
