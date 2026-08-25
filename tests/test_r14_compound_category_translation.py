import unittest
from unittest.mock import patch

import tools
from casper import browser


class CompoundCategoryTranslationTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    BAD_PRIMARY = {
        "product_query": "cup",
        "queries": ["corrupted output"],
        "requirements": [{"requirement": "cup", "source_phrase": "wrong"}],
        "localized_constraints": [],
    }
    BAD_RETRY = {
        "product_query": "cup",
        "queries": ["best rated cup high review count United States"],
        "requirements": [{"requirement": "cup", "source_phrase": "杯子"}],
        "localized_constraints": [],
    }

    def test_straw_cup_uses_narrow_translation_then_semantic_verification(self):
        translated = {
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "吸管杯",
            "english_category": "straw cup",
            "constraints": [],
        }
        verified = {
            "verdict": "MATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "吸管杯",
            "english_category": "straw cup",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[self.BAD_PRIMARY, self.BAD_RETRY, translated, verified],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐几个吸管杯",
                "",
                self.REGION,
                allow_category_translation_repair=True,
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "straw cup")
        self.assertEqual(plan["requirements"], ["straw cup"])
        self.assertIn("straw cup", plan["queries"][0])
        self.assertNotIn(" cup cup ", " " + plan["queries"][0] + " ")
        self.assertEqual(
            [call.args[0] for call in model.call_args_list],
            [
                "prompts/shopping_query.txt",
                "prompts/shopping_query_retry.txt",
                "prompts/shopping_category_translate.txt",
                "prompts/shopping_category_verify.txt",
            ],
        )
        self.assertIn("json_schema", model.call_args_list[2].kwargs)

    def test_other_compound_category_is_not_hardcoded_to_cups(self):
        bad_retry = dict(self.BAD_RETRY)
        bad_retry["product_query"] = "headphones"
        bad_retry["queries"] = [
            "best rated headphones high review count United States"
        ]
        translated = {
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "降噪耳机",
            "english_category": "noise-cancelling headphones",
            "constraints": [],
        }
        verified = {
            "verdict": "MATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "降噪耳机",
            "english_category": "noise-cancelling headphones",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[self.BAD_PRIMARY, bad_retry, translated, verified],
        ):
            plan = tools.build_shopping_plan(
                "推荐几个降噪耳机",
                "",
                self.REGION,
                allow_category_translation_repair=True,
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "noise-cancelling headphones")
        self.assertIn("noise-cancelling headphones", plan["queries"][0])

    def test_missing_explicit_constraint_still_fails_closed(self):
        translated = {
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "吸管杯",
            "english_category": "straw cup",
            "constraints": [],
        }
        missing = {
            "verdict": "MATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": ["500毫升"],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "吸管杯",
            "english_category": "straw cup",
        }
        old_repair_rejected = {
            "verdict": "MISMATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": ["500毫升"],
            "source_category_scope": "CURRENT_REQUEST",
            "source_category_phrase": "吸管杯",
            "english_category": "cup",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                self.BAD_PRIMARY,
                self.BAD_RETRY,
                translated,
                missing,
                old_repair_rejected,
            ],
        ):
            plan = tools.build_shopping_plan(
                "推荐500毫升吸管杯",
                "",
                self.REGION,
                allow_category_translation_repair=True,
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(plan["queries"], [])

    def test_translation_repair_is_opt_in_for_legacy_callers(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[self.BAD_PRIMARY, self.BAD_RETRY, {"verdict": "MISMATCH"}],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐几个吸管杯", "", self.REGION
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(model.call_count, 3)
        self.assertNotIn(
            "prompts/shopping_category_translate.txt",
            [call.args[0] for call in model.call_args_list],
        )

    def test_source_relevance_preserves_full_compound_category(self):
        self.assertFalse(
            browser._source_mentions_product_query(
                {"title": "Best cups", "description": "Our tested cup picks."},
                "straw cup",
            )
        )
        self.assertTrue(
            browser._source_mentions_product_query(
                {
                    "title": "Best straw cups",
                    "description": "Our tested straw cup picks.",
                },
                "straw cup",
            )
        )
        self.assertTrue(
            browser._source_mentions_product_query(
                {
                    "title": "Best noise canceling headphones",
                    "description": "Tested picks.",
                },
                "noise-cancelling headphones",
            )
        )


if __name__ == "__main__":
    unittest.main()
