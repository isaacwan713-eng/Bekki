import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

import tools
import shopping_region
from casper import browser


class ShoppingPlanIsolationTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    @staticmethod
    def valid_plan(**overrides):
        plan = {
            "merchant_scope": "regional_mix",
            "merchants": [],
            "product_query": "popular cup brands",
            "queries": ["popular cup brands high review count United States"],
            "requirements": [
                {"requirement": "cup", "source_phrase": "杯子"}
            ],
            "localized_constraints": [],
            "preference_profile": {
                "shopping_style": "unknown",
                "price_sensitivity": "unknown",
                "brand_strategy": "established_only",
                "reason": "explicit popularity request",
            },
        }
        plan.update(overrides)
        return plan

    @staticmethod
    def category_match(
        category="popular cup brands",
        source_phrase="杯子",
        source_scope="CURRENT_REQUEST",
    ):
        return {
            "verdict": "MATCH",
            "constraints_verdict": "COMPLETE",
            "unrepresented_constraint_source_phrases": [],
            "source_category_scope": source_scope,
            "source_category_phrase": source_phrase,
            "english_category": category,
        }

    def test_complete_request_excludes_stale_product_context(self):
        stale = "Cold Cup Longplay costs $35 and is durable; CLK-151 costs $13.60"
        raw = self.valid_plan(
            requirements=[
                {"requirement": "cup", "source_phrase": "杯子"},
                {"requirement": "durable", "source_phrase": "durable"},
            ],
            merchants=[
                {
                    "name": "Cold Cup Longplay",
                    "domain": "coldcuplongplay.com",
                    "reason": "stale",
                }
            ],
            localized_constraints=[
                {
                    "kind": "price",
                    "original": "$35",
                    "search_value": "$35",
                    "display_value": "$35",
                    "reason": "stale",
                }
            ],
        )
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[raw, self.category_match()],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", stale, self.REGION
            )
        planner_input = model.call_args_list[0].args[1]
        self.assertNotIn("Cold Cup", planner_input)
        self.assertNotIn("$35", planner_input)
        self.assertEqual(plan["context_scope"], "CURRENT_ONLY")
        self.assertEqual(plan["merchants"], [])
        self.assertEqual(plan["localized_constraints"], [])
        self.assertNotIn("durable", plan["requirements"])
        self.assertNotIn("premium", json.dumps(plan["preference_profile"]))
        self.assertEqual(plan["popularity_requirement"], "CURRENTLY_TRENDING")
        self.assertIn(
            "current cross-source brand trend evidence",
            plan["requirements"],
        )

    def test_candidate_count_and_raw_popularity_do_not_become_product_requirements(self):
        raw = self.valid_plan(
            requirements=[
                {"requirement": "cup", "source_phrase": "杯子"},
                {"requirement": "trending brand", "source_phrase": "网红牌子"},
                {"requirement": "three different candidates", "source_phrase": "三个"},
            ]
        )
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[raw, self.category_match()],
        ):
            plan = tools.build_shopping_plan(
                "给我推荐三个网红牌子杯子", "", self.REGION
            )
        self.assertEqual(
            plan["requirements"],
            ["cup", "current cross-source brand trend evidence"],
        )

    def test_referential_request_receives_only_bounded_recent_context(self):
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[
                self.valid_plan(
                    product_query="affordable cups",
                    queries=["affordable cups high review count United States"],
                ),
                self.category_match(
                    "affordable cups",
                    "insulated cups",
                    "RECENT_CONTEXT",
                ),
            ],
        ) as model:
            plan = tools.build_shopping_plan(
                "那换成便宜一点的三个",
                "The previous products were insulated cups.",
                self.REGION,
            )
        packet = json.loads(model.call_args_list[0].args[1])
        self.assertEqual(plan["context_scope"], "NEEDS_CONTEXT")
        self.assertIn("recent_context_for_reference", packet)
        self.assertNotIn("resolved_state", packet)
        self.assertNotIn("preference_context", packet)
        verify_packet = json.loads(model.call_args_list[1].args[1])
        self.assertEqual(verify_packet["context_scope"], "NEEDS_CONTEXT")
        self.assertIn("insulated cups", verify_packet["recent_context_for_reference"])

    def test_us_market_retries_non_executable_chinese_queries(self):
        invalid = self.valid_plan(
            product_query="杯子 United States",
            queries=["高评分高评论数杯子 United States"],
        )
        valid = self.valid_plan()
        with patch.object(
            tools,
            "run_ai_prompt",
            side_effect=[invalid, valid, self.category_match()],
        ) as model:
            plan = tools.build_shopping_plan(
                "给我推荐三个杯子", "", self.REGION
            )
        self.assertEqual(model.call_count, 3)
        self.assertEqual(plan["product_query"], "popular cup brands")
        self.assertTrue(all(any(ch.isascii() and ch.isalpha() for ch in query) for query in plan["queries"]))

    def test_us_single_word_product_category_is_valid(self):
        raw = self.valid_plan(
            product_query="headphones",
            queries=["popular headphones United States"],
        )
        self.assertTrue(
            tools._shopping_query_contract_is_usable(
                raw, "recommend headphones", self.REGION, "NONE"
            )
        )

    def test_us_country_name_does_not_make_a_chinese_query_executable(self):
        raw = self.valid_plan(
            product_query="杯子 United States",
            queries=["热门杯子 United States"],
        )
        self.assertFalse(
            tools._shopping_query_contract_is_usable(
                raw, "推荐杯子", self.REGION, "NONE"
            )
        )

    def test_popularity_intent_enums_are_current_turn_owned(self):
        cases = {
            "给我三个网红杯子": "CURRENTLY_TRENDING",
            "推荐三个主流大牌杯子": "ESTABLISHED_BRAND",
            "popular best-selling cups": "PROVEN_DEMAND",
            "给我三个普通杯子": "NONE",
            "不要网红牌子，要小众杯子": "NONE",
            "不要网红，要主流杯子": "ESTABLISHED_BRAND",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                actual, _phrase = tools._shopping_popularity_requirement(message)
                self.assertEqual(actual, expected)

    def test_complete_new_turn_markers_do_not_reopen_old_context(self):
        for message in (
            "这次给我推荐三个网红杯子",
            "我之前没买过保温杯，推荐三个主流款",
        ):
            with self.subTest(message=message):
                self.assertEqual(tools._shopping_context_scope(message), "CURRENT_ONLY")

    def test_explicit_deictic_follow_up_still_receives_context(self):
        for message in (
            "这款便宜吗",
            "那种还有别的颜色吗",
            "这一个怎么样",
            "is this one cheaper",
        ):
            with self.subTest(message=message):
                self.assertEqual(tools._shopping_context_scope(message), "NEEDS_CONTEXT")


class ShoppingEvidenceTests(unittest.TestCase):
    def test_us_engine_plan_is_fixed_and_never_uses_ai(self):
        model = Mock(
            side_effect=[
                {"engines": ["bing_cn", "baidu"], "reason": "invalid"},
                {"engines": ["google", "bing"], "reason": "US coverage"},
            ]
        )
        browser._ai_search_engine_policy.cache_clear()
        uncached_region = {
            "country_code": "US",
            "country_name": "United States",
            "location_name": "",
            "time_zone": "",
            "source": "test_uncached",
            "confidence": "high",
            "preferred_search_engines": [],
        }
        with patch.object(
            browser, "_detected_search_region", return_value=uncached_region
        ), patch.dict(
            sys.modules,
            {"tools": types.SimpleNamespace(run_ai_prompt=model)},
        ):
            engines = browser._search_engine_policy("US", "热门杯子")
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_engine_planner_ollama_500_is_bypassed_by_fixed_pair(self):
        model = Mock(side_effect=RuntimeError("ollama 500"))
        browser._ai_search_engine_policy.cache_clear()
        uncached_region = {
            "country_code": "US",
            "country_name": "United States",
            "location_name": "",
            "time_zone": "",
            "source": "test_uncached",
            "confidence": "high",
            "preferred_search_engines": [],
        }
        with patch.object(
            browser, "_detected_search_region", return_value=uncached_region
        ), patch.dict(
            sys.modules,
            {"tools": types.SimpleNamespace(run_ai_prompt=model)},
        ):
            engines = browser._search_engine_policy("US", "popular cups")
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_brand_evidence_requires_visible_distinct_domains(self):
        sources = [
            {"index": 1, "domain": "review-a.test", "title": "Alpha Cup is viral on TikTok in 2026", "description": "Alpha is trending", "url": "https://review-a.test/a"},
            {"index": 2, "domain": "review-b.test", "title": "Trending cup brands: Alpha", "description": "Alpha social media popularity", "url": "https://review-b.test/a"},
            {"index": 3, "domain": "review-c.test", "title": "Other products", "description": "No named brand", "url": "https://review-c.test/c"},
        ]
        result = {
            "brands": [
                {
                    "name": "Alpha",
                    "sources": [
                        {"source_index": 1, "support": "Alpha Cup is viral on TikTok in 2026"},
                        {"source_index": 2, "support": "Trending cup brands: Alpha"},
                    ],
                },
                {
                    "name": "Invented",
                    "sources": [
                        {"source_index": 1, "support": "Alpha Cup is viral on TikTok in 2026"},
                        {"source_index": 3, "support": "Other products"},
                    ],
                },
            ]
        }
        verified = browser._validate_brand_evidence(
            result, sources, 2, "CURRENTLY_TRENDING"
        )
        self.assertEqual([item["name"] for item in verified], ["Alpha"])
        self.assertEqual(verified[0]["source_count"], 2)

    def test_brand_evidence_deduplicates_canonical_aliases(self):
        sources = [
            {"index": 1, "domain": "one.test", "title": "Stanley and Stanley 1913 are mainstream brands", "description": "Stanley cup", "url": "https://one.test/a"},
            {"index": 2, "domain": "two.test", "title": "Stanley is a well-known brand; Stanley 1913 is a well-known brand", "description": "Stanley", "url": "https://two.test/a"},
        ]
        result = {
            "brands": [
                {
                    "name": "Stanley",
                    "sources": [
                        {"source_index": 1, "support": "Stanley and Stanley 1913 are mainstream brands"},
                        {"source_index": 2, "support": "Stanley is a well-known brand"},
                    ],
                },
                {
                    "name": "Stanley 1913",
                    "sources": [
                        {"source_index": 1, "support": "Stanley and Stanley 1913 are mainstream brands"},
                        {"source_index": 2, "support": "Stanley 1913 is a well-known brand"},
                    ],
                },
            ]
        }
        verified = browser._validate_brand_evidence(
            result, sources, 2, "ESTABLISHED_BRAND"
        )
        self.assertEqual([item["name"] for item in verified], ["Stanley"])

    def test_brand_mentions_without_positive_popularity_support_fail_closed(self):
        sources = [
            {"index": 1, "domain": "one.test", "title": "Alpha product page", "description": "Alpha cup", "url": "https://one.test/a"},
            {"index": 2, "domain": "two.test", "title": "Alpha catalog", "description": "Alpha cup colors", "url": "https://two.test/a"},
        ]
        result = {
            "brands": [
                {
                    "name": "Alpha",
                    "sources": [
                        {"source_index": 1, "support": "Alpha product page"},
                        {"source_index": 2, "support": "Alpha catalog"},
                    ],
                }
            ]
        }
        self.assertEqual(
            browser._validate_brand_evidence(
                result, sources, 2, "CURRENTLY_TRENDING"
            ),
            [],
        )

    def test_one_brands_popularity_cannot_be_transferred_to_another_brand(self):
        sources = [
            {"index": 1, "domain": "one.test", "title": "Alpha is trending; NicheCo catalog", "description": "NicheCo cups", "url": "https://one.test/a"},
            {"index": 2, "domain": "two.test", "title": "Alpha went viral; NicheCo products", "description": "NicheCo colors", "url": "https://two.test/a"},
        ]
        result = {
            "brands": [
                {
                    "name": "NicheCo",
                    "sources": [
                        {"source_index": 1, "support": "Alpha is trending"},
                        {"source_index": 2, "support": "Alpha went viral"},
                    ],
                }
            ]
        }
        self.assertEqual(
            browser._validate_brand_evidence(
                result, sources, 2, "CURRENTLY_TRENDING"
            ),
            [],
        )

    def test_negative_or_same_publisher_trend_mentions_do_not_count(self):
        negative_sources = [
            {"index": 1, "domain": "one.test", "title": "Alpha is not currently trending", "description": "Alpha cup", "url": "https://one.test/a"},
            {"index": 2, "domain": "two.test", "title": "Alpha is never viral", "description": "Alpha cup", "url": "https://two.test/a"},
        ]
        negative_result = {
            "brands": [
                {
                    "name": "Alpha",
                    "sources": [
                        {"source_index": 1, "support": "Alpha is not currently trending"},
                        {"source_index": 2, "support": "Alpha is never viral"},
                    ],
                }
            ]
        }
        self.assertEqual(
            browser._validate_brand_evidence(
                negative_result, negative_sources, 2, "CURRENTLY_TRENDING"
            ),
            [],
        )

        same_publisher = [
            {"index": 1, "domain": "reviews.example.com", "title": "Alpha went viral", "description": "Alpha trending", "url": "https://reviews.example.com/a"},
            {"index": 2, "domain": "news.example.com", "title": "Alpha is trending", "description": "Alpha viral cup", "url": "https://news.example.com/a"},
        ]
        same_result = {
            "brands": [
                {
                    "name": "Alpha",
                    "sources": [
                        {"source_index": 1, "support": "Alpha went viral"},
                        {"source_index": 2, "support": "Alpha is trending"},
                    ],
                }
            ]
        }
        self.assertEqual(
            browser._validate_brand_evidence(
                same_result, same_publisher, 2, "CURRENTLY_TRENDING"
            ),
            [],
        )

    def test_selection_is_grounded_and_brand_diverse(self):
        verified = [
            {"name": name, "source_count": 2, "source_domains": ["a.test", "b.test"]}
            for name in ("Alpha", "Beta", "Gamma")
        ]
        plan = {
            "popularity_requirement": "CURRENTLY_TRENDING",
            "verified_brand_evidence": verified,
        }
        base = {
            "page_type": "PRODUCT",
            "is_product_detail_url": True,
            "popularity_status": "HIGH",
            "popularity_evidence": "review_count: 2000",
            "review_count": "2000",
            "evidence_quality": "HIGH",
            "fit_score": 90,
            "source_score": 80,
        }
        products = [
            dict(base, brand="Alpha", product_title="Alpha One"),
            dict(base, brand="Alpha", product_title="Alpha Two", review_count="5000"),
            dict(base, brand="Beta", product_title="Beta One"),
            dict(base, brand="Gamma", product_title="Gamma One"),
            dict(base, brand="Unknown Niche", product_title="Niche"),
        ]
        selected = browser._select_shopping_products("popular cups", plan, products)
        brands = [products[index - 1]["brand"] for index in selected]
        self.assertEqual(len(brands), 3)
        self.assertEqual(len(set(brands)), 3)
        self.assertNotIn("Unknown Niche", brands)

    def test_selection_rejects_a_brand_that_misses_the_product_requirement(self):
        plan = {
            "popularity_requirement": "ESTABLISHED_BRAND",
            "requirements": ["stainless steel cup", "established brand evidence"],
            "verified_brand_evidence": [
                {"name": "Alpha", "source_count": 2, "source_domains": ["a.test", "b.test"]},
                {"name": "Beta", "source_count": 2, "source_domains": ["a.test", "b.test"]},
            ],
        }
        base = {
            "page_type": "PRODUCT",
            "is_product_detail_url": True,
            "popularity_status": "HIGH",
            "popularity_evidence": "review_count: 2000",
            "review_count": "2000",
            "evidence_quality": "HIGH",
            "fit_score": 90,
            "source_score": 80,
        }
        products = [
            dict(
                base,
                brand="Alpha",
                requirements=[
                    {"requirement": "stainless steel cup", "status": "MISMATCH"},
                    {"requirement": "established brand evidence", "status": "MATCH"},
                ],
            ),
            dict(
                base,
                brand="Beta",
                requirements=[
                    {"requirement": "stainless steel cup", "status": "MATCH"},
                    {"requirement": "established brand evidence", "status": "MATCH"},
                ],
            ),
        ]
        selected = browser._select_shopping_products("steel cups", plan, products)
        self.assertEqual(selected, [2])

    def test_brand_aliases_cannot_fill_multiple_slots(self):
        verified = [
            {"name": name, "source_count": 2, "source_domains": ["a.test", "b.test"]}
            for name in ("Stanley", "Beta", "Gamma")
        ]
        plan = {
            "popularity_requirement": "ESTABLISHED_BRAND",
            "verified_brand_evidence": verified,
        }
        base = {
            "page_type": "PRODUCT",
            "is_product_detail_url": True,
            "popularity_status": "HIGH",
            "popularity_evidence": "review_count: 2000",
            "review_count": "2000",
            "evidence_quality": "HIGH",
            "fit_score": 90,
            "source_score": 80,
        }
        products = [
            dict(base, brand="Stanley"),
            dict(base, brand="Stanley 1913"),
            dict(base, brand="Stan"),
            dict(base, brand="Beta"),
            dict(base, brand="Gamma"),
        ]
        selected = browser._select_shopping_products("cups", plan, products)
        brands = [products[index - 1]["brand"] for index in selected]
        self.assertEqual(len(brands), 3)
        self.assertEqual(sum(value.startswith("Stanley") for value in brands), 1)
        self.assertNotIn("Stan", brands)

    def test_proven_demand_can_be_grounded_by_the_product_page(self):
        plan = {
            "popularity_requirement": "PROVEN_DEMAND",
            "requirements": ["cup", "visible demand or review-count evidence"],
            "verified_brand_evidence": [],
        }
        product = {
            "page_type": "PRODUCT",
            "is_product_detail_url": True,
            "brand": "Alpha",
            "popularity_status": "HIGH",
            "popularity_evidence": "review_count: 2400",
            "review_count": "2400",
            "evidence_quality": "HIGH",
            "fit_score": 90,
            "source_score": 80,
            "requirements": [
                {"requirement": "cup", "status": "MATCH"},
                {
                    "requirement": "visible demand or review-count evidence",
                    "status": "MATCH",
                },
            ],
        }
        self.assertEqual(
            browser._select_shopping_products("popular cups", plan, [product]),
            [1],
        )

    def test_single_extraction_failure_preserves_other_results(self):
        item = {"page_type": "PRODUCT"}
        with patch.object(
            browser,
            "_extract_shopping_products_batch",
            side_effect=[{1: item}, RuntimeError("ollama 500"), {1: item}],
        ):
            result = browser._extract_shopping_products(
                "cups", {}, {}, [{}, {}, {}]
            )
        self.assertEqual(set(result), {1, 3})

    def test_extraction_downgrades_ungrounded_product_claims(self):
        plan = {
            "requirements": ["cup", "stainless steel"],
            "verified_brand_evidence": [],
        }
        raw = {
            "items": [
                {
                    "index": 1,
                    "page_type": "PRODUCT",
                    "title": "Invented Titanium Dishwasher Cup",
                    "summary": "Dishwasher-safe titanium construction",
                    "merchant": "Invented Merchant",
                    "price": "$20",
                    "currency": "USD",
                    "stock": "In stock",
                    "brand": "Alpha",
                    "rating": "4.8",
                    "review_count": "2000",
                    "popularity": {"status": "HIGH", "evidence": "2000 reviews"},
                    "requirements": [
                        {"requirement": "cup", "status": "MATCH", "evidence": "Alpha Cup"},
                        {"requirement": "stainless steel", "status": "MATCH", "evidence": "titanium construction"},
                    ],
                    "fit_score": 99,
                    "evidence_quality": "HIGH",
                    "reason": "invented",
                }
            ]
        }
        candidate = {
            "title": "Alpha Cup",
            "description": "Alpha Cup with 2000 reviews for $20",
            "domain": "merchant.test",
            "page_success": True,
            "page_content": "Alpha Cup. Price $20. 2000 reviews.",
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            result = browser._extract_shopping_products_batch(
                "recommend a cup", plan, {"country_code": "US"}, [candidate]
            )
        item = result[1]
        self.assertEqual(item["title"], "Alpha Cup")
        self.assertEqual(item["summary"], candidate["description"])
        self.assertEqual(item["merchant"], "merchant.test")
        self.assertEqual(item["stock"], "")
        self.assertEqual(item["currency"], "")
        self.assertEqual(item["requirements"][0]["status"], "MATCH")
        self.assertEqual(item["requirements"][1]["status"], "UNKNOWN")

    def test_failed_page_cannot_become_a_product(self):
        raw = {
            "items": [
                {
                    "index": 1,
                    "page_type": "PRODUCT",
                    "requirements": [],
                    "fit_score": 100,
                }
            ]
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            result = browser._extract_shopping_products_batch(
                "cups",
                {"requirements": []},
                {},
                [{"page_success": False, "title": "Invented"}],
            )
        self.assertIsNone(result)

    def test_related_product_brand_cannot_hijack_the_primary_product(self):
        verified = [
            {
                "name": "Stanley",
                "source_count": 2,
                "source_domains": ["one.test", "two.test"],
            }
        ]
        plan = {
            "requirements": ["cup", "current cross-source brand trend evidence"],
            "popularity_requirement": "CURRENTLY_TRENDING",
            "verified_brand_evidence": verified,
        }
        raw = {
            "items": [
                {
                    "index": 1,
                    "page_type": "PRODUCT",
                    "title": "NicheCo Cup",
                    "summary": "NicheCo cup",
                    "merchant": "merchant.test",
                    "price": "$20",
                    "currency": "",
                    "stock": "",
                    "brand": "Stanley",
                    "rating": "",
                    "review_count": "2000",
                    "popularity": {"status": "HIGH", "evidence": "2000 reviews"},
                    "requirements": [
                        {"requirement": "cup", "status": "MATCH", "evidence": "NicheCo Cup"},
                        {"requirement": "current cross-source brand trend evidence", "status": "MATCH", "evidence": "Stanley trend evidence"},
                    ],
                    "fit_score": 90,
                    "evidence_quality": "HIGH",
                    "reason": "",
                }
            ]
        }
        candidate = {
            "title": "NicheCo Cup",
            "description": "NicheCo Cup for $20",
            "domain": "merchant.test",
            "page_success": True,
            "page_content": "You may also like Stanley Cup with 2000 reviews",
            "structured_product": json.dumps(
                {
                    "@type": "Product",
                    "name": "NicheCo Cup",
                    "brand": {"name": "NicheCo"},
                }
            ),
        }
        with patch.object(tools, "run_ai_prompt", return_value=raw):
            result = browser._extract_shopping_products_batch(
                "trending cups", plan, {"country_code": "US"}, [candidate]
            )
        item = result[1]
        self.assertEqual(item["brand"], "NicheCo")
        self.assertEqual(item["review_count"], "")
        self.assertEqual(item["requirements"][1]["status"], "UNKNOWN")
        item["is_product_detail_url"] = True
        self.assertEqual(
            browser._select_shopping_products("trending cups", plan, [item]),
            [],
        )

    def test_scored_candidates_keep_each_verified_brand_in_the_extract_budget(self):
        scored = []
        for key, score in (("alpha", 100), ("beta", 80), ("gamma", 60)):
            for index in range(4):
                scored.append(
                    {
                        "shopping_query_key": key,
                        "source_score": score - index,
                        "url": f"https://merchant.test/{key}/{index}",
                    }
                )
        scored.sort(key=lambda item: item["source_score"], reverse=True)
        balanced = browser._balanced_shopping_candidates(
            scored, ["alpha", "beta", "gamma"], limit=6
        )
        keys = [item["shopping_query_key"] for item in balanced]
        self.assertEqual(keys.count("alpha"), 2)
        self.assertEqual(keys.count("beta"), 2)
        self.assertEqual(keys.count("gamma"), 2)

    def test_editorial_roundup_is_not_a_merchant_fallback(self):
        editorial = {
            "domain": "reviews.test",
            "title": "The 8 Best Cups to Buy in 2026",
            "description": "Comparison and buying guide",
            "url": "https://reviews.test/best-cups",
        }
        official = {
            "domain": "alpha.test",
            "title": "Alpha Official Store",
            "description": "Shop online and add to cart",
            "url": "https://alpha.test/products/cup",
        }
        self.assertLess(browser._merchant_source_priority(editorial), 0)
        self.assertGreaterEqual(browser._merchant_source_priority(official), 0)

    def test_search_engine_exception_keeps_next_engine_result(self):
        with patch.object(
            browser,
            "search_web",
            side_effect=[
                RuntimeError("engine failed"),
                {
                    "status": "OK",
                    "results": [
                        {
                            "title": "Result",
                            "description": "Product",
                            "domain": "merchant.test",
                            "url": "https://merchant.test/product",
                        }
                    ],
                },
            ],
        ):
            result = browser.discover_web(
                "popular cups",
                country_code="US",
                engine_plan=("google", "bing"),
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["results"]), 1)

    def test_shopping_task_plans_engines_once_and_reuses_pair(self):
        plan = {
            "planning_failed": False,
            "merchant_scope": "regional_mix",
            "merchants": [],
            "product_query": "cups",
            "queries": ["popular cups high review count"],
            "requirements": ["cup"],
            "popularity_requirement": "NONE",
            "preference_profile": {},
        }
        region = {"country_code": "US", "country_name": "United States"}
        with patch.object(tools, "unload_model"), patch.object(
            tools, "build_shopping_plan", return_value=plan
        ), patch.object(
            browser,
            "_plan_exact_purchase_lookup",
            return_value={"lookup_mode": "OPEN_ENDED"},
        ), patch.object(
            shopping_region,
            "detect_shopping_region",
            return_value=region,
            create=True,
        ), patch.object(
            browser, "_search_engine_policy", return_value=("google", "bing")
        ) as engine_policy, patch.object(
            browser, "_discover_popular_brands", return_value=[]
        ) as brand_discovery, patch.object(
            browser,
            "_discover_shopping_merchants",
            return_value={
                "status": "OK",
                "merchants": [{"name": "Merchant", "domain": "merchant.test"}],
            },
        ) as merchant_discovery, patch.object(
            browser,
            "discover_web",
            return_value={"status": "NO_RESULTS", "results": []},
        ) as discover:
            result = browser.shopping_research_controller("recommend cups")
        self.assertEqual(result["status"], "NO_RESULTS")
        engine_policy.assert_called_once()
        self.assertEqual(
            brand_discovery.call_args.args[3], ("google", "bing")
        )
        self.assertEqual(
            merchant_discovery.call_args.kwargs["engine_plan"],
            ("google", "bing"),
        )
        self.assertTrue(discover.call_args_list)
        for call in discover.call_args_list:
            self.assertEqual(call.kwargs["engine_plan"], ("google", "bing"))
            self.assertEqual(call.kwargs["country_code"], "US")


if __name__ == "__main__":
    unittest.main()
