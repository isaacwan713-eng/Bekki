import unittest
from datetime import datetime
from unittest.mock import patch

import tools


class GenericShoppingRepairTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    @staticmethod
    def live_bad_outputs(category="cup"):
        primary = {
            "product_query": category,
            "queries": [category, f"best rated {category}", f"high review count {category}"],
            "popularity_requirement": "NONE",
            "requirements": [
                {"requirement": "best-selling", "source_phrase": category},
                {"requirement": "high-review", "source_phrase": category},
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": category,
            "queries": [category, category],
            "requirements": [
                {"requirement": "normalized category", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        return primary, retry

    @staticmethod
    def category_match(category, source_phrase):
        return {
            "verdict": "MATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": source_phrase,
            "english_category": category,
        }

    def test_live_generic_cup_outputs_recover_before_search(self):
        primary, retry = self.live_bad_outputs()
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个杯子",
                "上一轮预算$35且要求耐用",
                self.REGION,
            )
        self.assertEqual(model.call_count, 3)
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "cup")
        self.assertEqual(
            plan["queries"],
            ["cup best rated high review count United States"],
        )
        self.assertEqual(plan["requirements"], ["cup"])
        self.assertNotIn("35", plan["queries"][0])
        self.assertNotIn("durable", plan["queries"][0])

    def test_generic_repair_is_not_cup_hardcoded(self):
        primary, retry = self.live_bad_outputs("headphones")
        retry["requirements"] = [
            {"requirement": "normalized category", "source_phrase": "耳机"}
        ]
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                primary,
                retry,
                self.category_match("headphones", "耳机"),
            ],
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个耳机", "", self.REGION
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "headphones")
        self.assertIn("headphones best rated high review count", plan["queries"][0])

    def test_same_wrong_category_still_fails_semantic_verification(self):
        primary, retry = self.live_bad_outputs("running shoes")
        mismatch = {
            "verdict": "MISMATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "杯子",
            "english_category": "running shoes",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, mismatch],
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个杯子", "", self.REGION
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(plan["queries"], [])

    def test_missing_explicit_constraint_still_fails_closed(self):
        primary, retry = self.live_bad_outputs()
        missing = {
            "verdict": "MATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": ["不锈钢"],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "杯子",
            "english_category": "cup",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, missing],
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个不锈钢杯子", "", self.REGION
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(plan["queries"], [])


if __name__ == "__main__":
    unittest.main()
