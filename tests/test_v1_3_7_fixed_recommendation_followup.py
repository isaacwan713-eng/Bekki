import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from casper import recommendation


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_main_name_functions():
    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    names = {
        "recommendation_name_placeholders",
        "_substitute_candidate_names",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {}
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace


class FixedRecommendationFollowupTests(unittest.TestCase):
    def fixed_plan_raw(self):
        return {
            "location": "San Gabriel, California",
            "target_country": "United States",
            "query_language": "en",
            "fallback_languages": ["zh-CN"],
            "source_strategy": "Search only the three prior restaurants.",
            "target_option_count": 3,
            "candidate_scope": "FIXED",
            "allowed_candidate_names": [
                "Beijing Tasty House",
                "小陸子清粥店",
                "小美快餐‧小吃‧冰果",
            ],
            "requirements": [
                "Suitable for elderly individuals",
                "Suitable for a 2-year-old child",
            ],
            "comparison_criteria": ["accessibility", "child-friendliness"],
            "preferred_sources": [],
            "queries": [
                "Beijing Tasty House elderly child",
                "小陸子清粥店 老人 小孩",
                "小美快餐‧小吃‧冰果 老人 小孩",
            ],
            "reason": "The user refers to the prior three restaurants.",
        }

    def test_ai_fixed_scope_is_grounded_and_bypasses_open_query_review(self):
        recent = (
            "Bekki: Beijing Tasty House、小陸子清粥店和"
            "小美快餐‧小吃‧冰果。"
        )
        with patch.object(recommendation, "_ai", return_value=self.fixed_plan_raw()) as ai:
            plan = recommendation._plan(
                "这三家里面哪家更适合老人和两岁小朋友一起去？",
                "RESTAURANT",
                {},
                recent,
            )
        self.assertEqual(plan["candidate_scope"], "FIXED")
        self.assertEqual(
            plan["allowed_candidate_names"],
            self.fixed_plan_raw()["allowed_candidate_names"],
        )
        self.assertEqual(plan["target_option_count"], 3)
        self.assertEqual(ai.call_count, 1)

    def test_fixed_query_set_covers_each_original_candidate(self):
        plan = {
            **self.fixed_plan_raw(),
            "queries": [],
        }
        queries = recommendation._fixed_query_set(
            plan,
            ["Beijing Tasty House reviews"],
        )
        self.assertEqual(len(queries), 3)
        for name in plan["allowed_candidate_names"]:
            self.assertTrue(any(name in query for query in queries))

    def test_fixed_extraction_rejects_substitute_restaurant(self):
        plan = self.fixed_plan_raw()
        extracted = {
            "is_real_candidate": True,
            "title": "Blossom Market Hall",
            "summary": "A different restaurant.",
            "requirements": [],
            "sections": [],
            "unknowns": [],
        }
        with patch.object(recommendation, "_ai", return_value=extracted):
            result = recommendation._extract_one(
                "这三家里面哪家更适合？",
                "RESTAURANT",
                plan,
                {"title": "Guide", "url": "https://example.test"},
                {"content": "Blossom Market Hall", "image_url": ""},
            )
        self.assertIsNone(result)

    def test_restaurant_name_token_restores_exact_source_title(self):
        namespace = _load_main_name_functions()
        placeholders = namespace["recommendation_name_placeholders"](
            {
                "recommendation_domain": "RESTAURANT",
                "cards": [{"title": "Beijing Tasty House"}],
            },
            "RECOMMENDATION_RESEARCH",
        )
        self.assertEqual(
            placeholders,
            [{
                "token": "[[BEKKI_RESTAURANT_1]]",
                "title": "Beijing Tasty House",
            }],
        )
        hidden = namespace["_substitute_candidate_names"](
            "Beijing Tasty House is the strongest candidate.",
            placeholders,
        )
        self.assertNotIn("Beijing Tasty House", hidden)
        restored = namespace["_substitute_candidate_names"](
            "推荐 [[BEKKI_RESTAURANT_1]]。",
            placeholders,
            restore=True,
        )
        self.assertEqual(restored, "推荐 Beijing Tasty House。")


if __name__ == "__main__":
    unittest.main()
