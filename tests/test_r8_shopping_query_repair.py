import re
import unittest
from datetime import datetime
from unittest.mock import patch

import shopping_region
import tools
from casper import browser


class ShoppingQueryRepairTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    @staticmethod
    def bad_cup_outputs():
        primary = {
            "product_query": "Korean celebrity cup",
            "queries": [
                "Korean celebrity cup",
                "K-pop star cup",
                "Celebrity cup",
            ],
            "popularity_requirement": "CURRENTLY_TRENDING",
            "requirements": [
                {"requirement": "size", "source_phrase": "杯子"},
                {"requirement": "brand", "source_phrase": "网红"},
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "cup",
            "queries": ["netred cup", "netred cup", "netred cup"],
            "requirements": [
                {"requirement": "normalized category", "source_phrase": "网红"}
            ],
            "localized_constraints": [],
        }
        return primary, retry

    @staticmethod
    def category_match(category, source_phrase, source_scope="CURRENT_REQUEST"):
        return {
            "verdict": "MATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": source_scope,
            "source_category_phrase": source_phrase,
            "english_category": category,
        }

    def test_real_log_outputs_recover_to_grounded_trending_cup_query(self):
        primary, retry = self.bad_cup_outputs()
        stale = "Cold Cup Longplay costs $35 and is durable"
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", stale, self.REGION
            )

        self.assertEqual(model.call_count, 3)
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["context_scope"], "CURRENT_ONLY")
        self.assertEqual(plan["product_query"], "cup")
        self.assertEqual(
            plan["queries"],
            [
                f"cup viral trending brands {datetime.now().year} "
                "United States"
            ],
        )
        self.assertEqual(
            plan["requirements"],
            ["cup", "current cross-source brand trend evidence"],
        )
        material = " ".join(plan["queries"]).casefold()
        self.assertFalse(re.search(r"[\u3400-\u9fff]", material))
        for forbidden in ("korean", "k-pop", "celebrity", "netred", "$35", "durable"):
            self.assertNotIn(forbidden, material)

    def test_repair_is_category_generic_not_cup_or_brand_hardcoding(self):
        primary = {
            "product_query": "internet celebrity headphones",
            "queries": ["celebrity headphones"],
            "requirements": [
                {"requirement": "category", "source_phrase": "耳机"}
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "headphones",
            "queries": ["netred headphones"],
            "requirements": [],
            "localized_constraints": [],
        }
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
                "给我推荐三个网红牌子耳机", "", self.REGION
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "headphones")
        self.assertIn("headphones viral trending brands", plan["queries"][0])

    def test_disagreeing_product_categories_still_fail_closed(self):
        primary, retry = self.bad_cup_outputs()
        retry["product_query"] = "headphones"
        retry["queries"] = ["netred headphones"]
        with patch.object(tools, "run_ai_prompt", side_effect=[primary, retry]):
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(plan["queries"], [])

    def test_negated_popularity_phrases_never_reverse_the_request(self):
        cases = (
            "不要太网红的杯子",
            "不想买网红杯子",
            "不想要太网红的杯子",
            "不是网红杯子",
            "不是主流品牌",
            "不是很热门的杯子",
            "没那么流行的杯子",
            "别推荐网红杯子",
            "不要买热门杯子",
            "非主流杯子",
            "不知名的杯子",
            "不热门的杯子",
            "不流行的杯子",
            "不畅销的杯子",
            "网红杯子除外",
            "do not recommend trending cups",
            "do not really want trending cups",
            "don't want viral cups",
            "don't really want viral cups",
            "anything but mainstream cups",
            "no viral brands",
            "without popular brands",
            "unpopular cups",
            "non-mainstream cups",
            "viral brands excluded",
            "viral cups not wanted",
        )
        for message in cases:
            with self.subTest(message=message):
                requirement, _phrase = tools._shopping_popularity_requirement(
                    message
                )
                self.assertEqual(requirement, "NONE")

    def test_unrelated_negation_does_not_hide_positive_popularity(self):
        cases = (
            ("不要贵的，但要网红杯子", "CURRENTLY_TRENDING"),
            ("不要塑料的，但要主流品牌杯子", "ESTABLISHED_BRAND"),
            ("网红杯子不要太贵", "CURRENTLY_TRENDING"),
            ("do not recommend expensive cups; I want trending cups", "CURRENTLY_TRENDING"),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                requirement, _phrase = tools._shopping_popularity_requirement(
                    message
                )
                self.assertEqual(requirement, expected)

    def test_negated_or_substring_merchants_never_become_exclusive(self):
        cases = (
            "不要Amazon，推荐网红杯子",
            "除了Amazon都可以",
            "not Amazon",
            "avoid Walmart",
            "不要京东",
            "不想在Amazon买",
            "拒绝Amazon",
            "不要Amazon和Walmart",
            "avoid Amazon and Walmart",
            "除了Amazon和Walmart都可以",
            "Amazon和Walmart比价",
            "Amazon or Walmart",
            "target audience gifts",
            "Amazonian coffee mug",
        )
        for message in cases:
            with self.subTest(message=message):
                self.assertIsNone(
                    tools._explicit_shopping_merchant(message, self.REGION)
                )

    def test_current_turn_merchant_scope_respects_positive_and_negative_mentions(self):
        raw = {
            "product_query": "cup",
            "queries": [
                "cup viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        for message, expected_scope, expected_merchants in (
            ("不要Amazon，推荐网红杯子", "regional_mix", []),
            ("只在Amazon买网红杯子", "exclusive", ["amazon.com"]),
        ):
            with self.subTest(message=message), patch.object(
                tools,
                "run_ai_prompt",
                side_effect=[raw, self.category_match("cup", "杯子")],
            ):
                plan = tools.build_shopping_plan(message, "", self.REGION)
            self.assertFalse(plan["planning_failed"])
            self.assertEqual(plan["merchant_scope"], expected_scope)
            self.assertEqual(
                [item["domain"] for item in plan["merchants"]],
                expected_merchants,
            )

    def test_same_wrong_english_category_needs_source_category_verification(self):
        primary = {
            "product_query": "celebrity cup",
            "queries": ["celebrity cup"],
            "requirements": [],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "cup",
            "queries": ["netred cup"],
            "requirements": [],
            "localized_constraints": [],
        }
        mismatch = {
            "verdict": "MISMATCH",
            "source_category_phrase": "",
            "english_category": "cup",
        }
        with patch.object(
            tools, "run_ai_prompt", side_effect=[primary, retry, mismatch]
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子耳机", "", self.REGION
            )
        self.assertTrue(plan["planning_failed"])
        self.assertEqual(plan["queries"], [])

    def test_recovery_rejects_any_missing_nonnumeric_hard_constraint(self):
        cases = (
            ("给我推荐三个不锈钢网红杯子", "不锈钢"),
            ("给我推荐三个红色网红杯子", "红色"),
            ("给我推荐三个适合露营的网红杯子", "适合露营"),
            ("给我推荐三个可放洗碗机的网红杯子", "可放洗碗机"),
        )
        for message, missing_phrase in cases:
            primary = {
                "product_query": "celebrity cup",
                "queries": ["celebrity cup"],
                "requirements": [],
                "localized_constraints": [],
            }
            retry = {
                "product_query": "cup",
                "queries": ["netred cup"],
                "requirements": [],
                "localized_constraints": [],
            }
            incomplete = {
                "verdict": "MATCH",
                "constraints_verdict": "MISSING",
                "unrepresented_constraint_source_phrases": [missing_phrase],
                "source_category_phrase": "杯子",
                "english_category": "cup",
            }
            with self.subTest(message=message), patch.object(
                tools,
                "run_ai_prompt",
                side_effect=[primary, retry, incomplete],
            ) as model:
                plan = tools.build_shopping_plan(message, "", self.REGION)
            self.assertEqual(model.call_count, 3)
            self.assertTrue(plan["planning_failed"])
            self.assertEqual(plan["queries"], [])

    def test_semantically_wrong_requirements_are_not_allowed_downstream(self):
        raw = {
            "product_query": "cup",
            "queries": [
                f"cup viral trending brands {datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "size", "source_phrase": "杯子"},
                {"requirement": "brand", "source_phrase": "网红"},
                {
                    "requirement": "normalized category",
                    "source_phrase": "网红",
                },
            ],
            "localized_constraints": [],
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 3)
        self.assertTrue(plan["planning_failed"])
        self.assertNotIn("size", plan["requirements"])
        self.assertNotIn("brand", plan["requirements"])
        self.assertNotIn("normalized category", plan["requirements"])

    def test_canonical_queries_with_two_bad_requirement_sets_can_recover(self):
        query = (
            f"cup viral trending brands {datetime.now().year} United States"
        )
        primary = {
            "product_query": "cup",
            "queries": [query],
            "requirements": [
                {"requirement": "size", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "cup",
            "queries": [query],
            "requirements": [
                {
                    "requirement": "normalized category",
                    "source_phrase": "杯子",
                }
            ],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 3)
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(
            plan["requirements"],
            ["cup", "current cross-source brand trend evidence"],
        )

    def test_unowned_product_query_modifiers_fail_closed(self):
        for modifier in ("premium", "ceramic", "large"):
            raw = {
                "product_query": f"{modifier} cup",
                "queries": [
                    f"{modifier} cup viral trending brands "
                    f"{datetime.now().year} United States"
                ],
                "requirements": [
                    {"requirement": "cup", "source_phrase": "杯子"}
                ],
                "localized_constraints": [],
            }
            with self.subTest(modifier=modifier), patch.object(
                tools, "run_ai_prompt", return_value=raw
            ):
                plan = tools.build_shopping_plan(
                    "给我推荐三个网红牌子杯子", "", self.REGION
                )
            self.assertTrue(plan["planning_failed"])
            self.assertNotIn(f"{modifier} cup", plan["requirements"])

    def test_cross_language_requirement_cannot_self_prove_a_modifier(self):
        raw = {
            "product_query": "premium cup",
            "queries": [
                f"premium cup viral trending brands {datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "premium", "source_phrase": "杯子"},
                {"requirement": "cup", "source_phrase": "杯子"},
            ],
            "localized_constraints": [],
        }
        mismatch = {
            "verdict": "MISMATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": ["杯子"],
            "source_category_phrase": "",
            "english_category": "premium cup",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[raw, mismatch, raw, mismatch, mismatch],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 5)
        self.assertTrue(plan["planning_failed"])
        self.assertNotIn("premium", plan["requirements"])

    def test_cultural_or_negated_words_do_not_authorize_celebrity_drift(self):
        messages = (
            "给我推荐三个韩国网红杯子",
            "不要韩国明星同款，只要三个网红杯子",
        )
        raw = {
            "product_query": "Korean celebrity cup",
            "queries": [
                f"Korean celebrity cup viral trending brands {datetime.now().year}"
            ],
            "requirements": [
                {"requirement": "Korean", "source_phrase": "韩国"},
                {"requirement": "celebrity", "source_phrase": "韩国"},
                {"requirement": "cup", "source_phrase": "杯子"},
            ],
            "localized_constraints": [],
        }
        mismatch = {
            "verdict": "MISMATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": [],
            "source_category_phrase": "",
            "english_category": "Korean celebrity cup",
        }
        for message in messages:
            with self.subTest(message=message), patch.object(
                tools,
                "run_ai_prompt",
                side_effect=[raw, mismatch, raw, mismatch, mismatch],
            ):
                plan = tools.build_shopping_plan(message, "", self.REGION)
            self.assertTrue(plan["planning_failed"])

    def test_each_query_must_contain_the_product_category(self):
        raw = {
            "product_query": "cup",
            "queries": [
                f"running shoes viral trending brands {datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        self.assertFalse(
            tools._shopping_query_contract_is_usable(
                raw,
                "给我推荐三个网红杯子",
                self.REGION,
                "CURRENTLY_TRENDING",
            )
        )

    def test_source_owned_constraint_survives_only_when_present_in_query(self):
        primary = {
            "product_query": "cup",
            "queries": ["netred stainless steel cup"],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"},
                {"requirement": "stainless steel", "source_phrase": "不锈钢"},
            ],
            "localized_constraints": [],
        }
        retry = dict(primary, queries=["internet celebrity stainless steel cup"])
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个不锈钢网红杯子", "", self.REGION
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(
            plan["requirements"],
            [
                "cup",
                "stainless steel",
                "current cross-source brand trend evidence",
            ],
        )
        self.assertIn("stainless steel", plan["queries"][0])

    def test_one_attempt_cannot_inject_a_color_constraint(self):
        primary = {
            "product_query": "celebrity cup",
            "queries": ["red celebrity cup"],
            "requirements": [
                {"requirement": "red", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "cup",
            "queries": ["netred cup"],
            "requirements": [],
            "localized_constraints": [],
        }
        with patch.object(tools, "run_ai_prompt", side_effect=[primary, retry]) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 2)
        self.assertTrue(plan["planning_failed"])
        self.assertNotIn("red", plan["requirements"])

    def test_popularity_substring_cannot_own_a_red_color_requirement(self):
        raw = {
            "product_query": "cup",
            "queries": [
                f"red cup viral trending brands {datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "red", "source_phrase": "红"}
            ],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[raw, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 2)
        self.assertTrue(plan["planning_failed"])
        self.assertNotIn("red", plan["requirements"])

    def test_valid_numeric_unit_and_currency_equivalents_are_retained(self):
        raw = {
            "product_query": "cup",
            "queries": [
                f"500 ml cup under $30 viral trending brands {datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"},
                {
                    "requirement": "500 milliliters",
                    "source_phrase": "500毫升",
                },
                {
                    "requirement": "under 30 dollars",
                    "source_phrase": "30美元以下",
                },
            ],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[raw, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个500毫升、30美元以下的网红杯子",
                "",
                self.REGION,
            )
        self.assertEqual(model.call_count, 2)
        self.assertFalse(plan["planning_failed"])
        self.assertIn("500 milliliters", plan["requirements"])
        self.assertIn("under 30 dollars", plan["requirements"])

    def test_opposite_budget_direction_and_wrong_unit_fail_closed(self):
        cases = (
            (
                "给我推荐三个30美元以上的网红杯子",
                "cup under 30 dollars viral trending brands "
                f"{datetime.now().year} United States",
                "under 30 dollars",
                "30美元以上",
            ),
            (
                "给我推荐三个500克的网红杯子",
                "500 milliliters cup viral trending brands "
                f"{datetime.now().year} United States",
                "500 milliliters",
                "500克",
            ),
        )
        for message, query, requirement, source_phrase in cases:
            raw = {
                "product_query": "cup",
                "queries": [query],
                "requirements": [
                    {"requirement": "cup", "source_phrase": "杯子"},
                    {
                        "requirement": requirement,
                        "source_phrase": source_phrase,
                    },
                ],
                "localized_constraints": [],
            }
            with self.subTest(message=message), patch.object(
                tools, "run_ai_prompt", return_value=raw
            ) as model:
                plan = tools.build_shopping_plan(message, "", self.REGION)
            self.assertEqual(model.call_count, 2)
            self.assertTrue(plan["planning_failed"])
            self.assertNotIn(requirement, plan["requirements"])

    def test_single_character_chinese_categories_can_be_verified(self):
        cases = (("鞋", "shoes"), ("包", "bags"), ("表", "watches"), ("杯", "cups"))
        for source_phrase, category in cases:
            raw = self.category_match(category, source_phrase)
            with self.subTest(source_phrase=source_phrase):
                self.assertTrue(
                    tools._shopping_category_verification_is_usable(
                        raw,
                        f"推荐网红{source_phrase}",
                        category,
                    )
                )

    def test_unspaced_chinese_candidate_counts_are_not_product_constraints(self):
        cases = (
            ("推荐3个网红杯子", "cup", "杯子"),
            ("请找3款热门耳机", "headphones", "耳机"),
            ("推荐3双网红鞋", "shoes", "鞋"),
            ("请找3台热门电脑", "computers", "电脑"),
        )
        for message, category, source_phrase in cases:
            raw = {
                "product_query": category,
                "queries": [
                    f"{category} viral trending brands "
                    f"{datetime.now().year} United States"
                ],
                "requirements": [
                    {"requirement": category, "source_phrase": source_phrase}
                ],
                "localized_constraints": [],
            }
            with self.subTest(message=message), patch.object(
                tools,
                "run_ai_prompt",
                side_effect=[
                    raw,
                    self.category_match(category, source_phrase),
                ],
            ) as model:
                plan = tools.build_shopping_plan(message, "", self.REGION)
            self.assertEqual(model.call_count, 2)
            self.assertFalse(plan["planning_failed"])

    def test_multipack_numbers_remain_hard_constraints(self):
        for message in ("推荐3个装的杯子", "推荐3件套杯子", "推荐3只装的杯子"):
            with self.subTest(message=message):
                self.assertIn(
                    "3",
                    tools._shopping_hard_constraint_number_tokens(message),
                )

    def test_canonical_tokens_do_not_let_bad_primary_skip_recovery(self):
        primary = {
            "product_query": "Korean celebrity cup",
            "queries": [
                f"viral trending Korean celebrity cup {datetime.now().year}"
            ],
            "requirements": [
                {"requirement": "size", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        retry = {
            "product_query": "cup",
            "queries": ["netred cup"],
            "requirements": [],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 3)
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "cup")

    def test_explicit_current_category_beats_stale_referential_context(self):
        stale_primary = {
            "product_query": "running shoes",
            "queries": [
                "running shoes viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [],
            "localized_constraints": [],
        }
        current_retry = {
            "product_query": "cup",
            "queries": [
                "cup viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        semantic_mismatch = {
            "verdict": "MISMATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": "RECENT_CONTEXT",
            "source_category_phrase": "运动鞋",
            "english_category": "running shoes",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                stale_primary,
                semantic_mismatch,
                current_retry,
                self.category_match("cup", "杯子"),
            ],
        ) as model:
            plan = tools.build_shopping_plan(
                "同样给我推荐三个网红杯子",
                "上一轮推荐了运动鞋",
                self.REGION,
            )
        self.assertEqual(model.call_count, 4)
        self.assertEqual(plan["context_scope"], "NEEDS_CONTEXT")
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "cup")
        self.assertTrue(all("running shoes" not in q for q in plan["queries"]))
        verify_packet = model.call_args_list[1].args[1]
        self.assertIn('"context_scope":"NEEDS_CONTEXT"', verify_packet)
        self.assertIn("上一轮推荐了运动鞋", verify_packet)

    def test_recent_category_scope_is_only_valid_for_referential_turns(self):
        recent_match = self.category_match(
            "insulated cups",
            "insulated cups",
            "RECENT_CONTEXT",
        )
        self.assertTrue(
            tools._shopping_category_verification_is_usable(
                recent_match,
                "那换成便宜一点的三个",
                "insulated cups",
                "NEEDS_CONTEXT",
                "The previous products were insulated cups.",
            )
        )
        self.assertFalse(
            tools._shopping_category_verification_is_usable(
                recent_match,
                "给我推荐三个网红杯子",
                "insulated cups",
                "CURRENT_ONLY",
                "The previous products were insulated cups.",
            )
        )

    def test_referential_numeric_constraint_is_retained_from_bounded_context(self):
        raw = {
            "product_query": "insulated cup",
            "queries": [
                "500 ml insulated cup viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [
                {
                    "requirement": "insulated cup",
                    "source_phrase": "保温杯",
                },
                {
                    "requirement": "500 milliliters",
                    "source_phrase": "500毫升",
                },
            ],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                raw,
                self.category_match(
                    "insulated cup",
                    "保温杯",
                    "RECENT_CONTEXT",
                ),
            ],
        ) as model:
            plan = tools.build_shopping_plan(
                "同样再推荐三个网红的",
                "上一轮用户要500毫升保温杯",
                self.REGION,
            )
        self.assertEqual(model.call_count, 2)
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "insulated cup")
        self.assertIn("500 milliliters", plan["requirements"])
        self.assertIn("500 ml", plan["queries"][0])

    def test_stale_numeric_context_cannot_override_explicit_current_category(self):
        stale_primary = {
            "product_query": "cup",
            "queries": [
                "cup under $35 viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"},
                {"requirement": "under 35 dollars", "source_phrase": "$35"},
            ],
            "localized_constraints": [],
        }
        clean_retry = {
            "product_query": "cup",
            "queries": [
                "cup viral trending brands "
                f"{datetime.now().year} United States"
            ],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
        }
        semantic_reject = {
            "verdict": "MISMATCH",
            "constraints_verdict": "MISSING",
            "unrepresented_constraint_source_phrases": ["杯子"],
            "source_category_scope": "RECENT_CONTEXT",
            "source_category_phrase": "保温杯",
            "english_category": "cup",
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                stale_primary,
                semantic_reject,
                clean_retry,
                self.category_match("cup", "杯子"),
            ],
        ):
            plan = tools.build_shopping_plan(
                "同样给我推荐三个网红杯子",
                "上一轮要500毫升保温杯，预算$35",
                self.REGION,
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "cup")
        self.assertNotIn("35", " ".join(plan["queries"]))
        self.assertNotIn("under 35 dollars", plan["requirements"])

    def test_referential_product_model_year_is_allowed_but_current_only_injection_is_not(self):
        model_year_plan = {
            "product_query": "2024 MacBook Air",
            "queries": [
                "2024 MacBook Air popular models United States"
            ],
            "requirements": [
                {
                    "requirement": "2024 MacBook Air",
                    "source_phrase": "2024 MacBook Air",
                }
            ],
            "localized_constraints": [],
        }
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                model_year_plan,
                self.category_match(
                    "2024 MacBook Air",
                    "2024 MacBook Air",
                    "RECENT_CONTEXT",
                ),
            ],
        ):
            plan = tools.build_shopping_plan(
                "同样再来三个",
                "上一轮看的产品是2024 MacBook Air",
                self.REGION,
            )
        self.assertFalse(plan["planning_failed"])
        self.assertEqual(plan["product_query"], "2024 MacBook Air")
        self.assertFalse(
            tools._shopping_query_contract_is_usable(
                model_year_plan,
                "推荐三台热门笔记本电脑",
                self.REGION,
                "PROVEN_DEMAND",
            )
        )

    def test_recovered_plan_crosses_controller_planning_gate(self):
        primary, retry = self.bad_cup_outputs()
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[primary, retry, self.category_match("cup", "杯子")],
        ):
            recovered = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        with patch.object(
            tools, "build_shopping_plan", return_value=recovered
        ), patch.object(
            browser,
            "_plan_exact_purchase_lookup",
            return_value={"lookup_mode": "OPEN_ENDED"},
        ), patch.object(
            tools, "unload_model"
        ), patch.object(
            shopping_region, "detect_shopping_region", return_value=self.REGION
        ), patch.object(
            browser, "_search_engine_policy", return_value=("google", "bing")
        ) as engine_policy, patch.object(
            browser, "_discover_popular_brands", return_value=[]
        ):
            result = browser.shopping_research_controller(
                "给我推荐三个网红牌子杯子"
            )
        self.assertEqual(result["status"], "NO_BRAND_POPULARITY_EVIDENCE")
        engine_policy.assert_called_once_with("US", recovered["queries"][0])


if __name__ == "__main__":
    unittest.main()
