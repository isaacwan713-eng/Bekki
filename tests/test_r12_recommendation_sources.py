import json
import unittest
from unittest.mock import patch

import tools
from casper import browser


class RecommendationSourceTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    def test_generic_recommendation_language_is_positive_support(self):
        self.assertTrue(
            browser._popularity_support_is_positive(
                "Our best overall cup is the YETI Rambler.",
                "NONE",
            )
        )

    def test_long_roundup_keeps_distributed_recommendation_sections(self):
        content = (
            "navigation " * 400
            + " Best overall cup YETI Rambler is our tested pick. "
            + "details " * 300
            + " Budget pick Owala tumbler is recommended for daily use. "
        )
        excerpt = browser._recommendation_page_excerpt(content)
        self.assertIn("Best overall cup YETI", excerpt)
        self.assertIn("Budget pick Owala", excerpt)
        self.assertLessEqual(len(excerpt), 2400)
        self.assertTrue(
            browser._popularity_support_is_positive(
                "The Owala tumbler is our top pick for daily use.",
                "NONE",
            )
        )

    def test_generic_brand_can_be_a_grounded_single_source_lead(self):
        sources = [
            {
                "index": 1,
                "domain": "review.example",
                "title": "Best cups",
                "description": "Our best overall cup is the YETI Rambler.",
                "url": "https://review.example/cups",
                "published": "2026-08-01",
            }
        ]
        result = {"brands": [{"name": "YETI", "source_indexes": [1]}]}
        generic = browser._validate_brand_evidence(
            result, sources, 1, "NONE", "cup"
        )
        explicit_trend = browser._validate_brand_evidence(
            result, sources, 2, "CURRENTLY_TRENDING", "cup"
        )
        self.assertEqual([row["name"] for row in generic], ["YETI"])
        self.assertEqual(explicit_trend, [])

    def test_generic_discovery_reads_recommendation_pages_before_brand_indexes(self):
        discovery = {
            "status": "OK",
            "results": [
                {
                    "domain": "review-a.example",
                    "title": "Expert cup review",
                    "description": "We tested everyday drinkware.",
                    "url": "https://review-a.example/cups",
                },
                {
                    "domain": "review-b.example",
                    "title": "Cup comparison roundup",
                    "description": "Independent recommendations.",
                    "url": "https://review-b.example/cups",
                },
            ],
        }
        pages = [
            {
                "success": True,
                "content": "Our best overall cup is the YETI Rambler after testing.",
                "published": "2026-08-01",
            },
            {
                "success": True,
                "content": "The Owala tumbler is our top pick for everyday cups.",
                "published": "2026-07-20",
            },
        ]
        model_result = {
            "brands": [
                {"name": "YETI", "source_indexes": [1]},
                {"name": "Owala", "source_indexes": [2]},
            ]
        }
        with patch.object(browser, "discover_web", return_value=discovery), patch.object(
            browser, "read_url", side_effect=pages
        ) as reader, patch.object(
            tools, "run_ai_prompt", return_value=model_result
        ) as model:
            brands = browser._discover_popular_brands(
                "给我推荐三个杯子",
                {"product_query": "cup", "popularity_requirement": "NONE"},
                self.REGION,
                ("google", "bing"),
            )
        self.assertEqual(reader.call_count, 2)
        self.assertEqual([row["name"] for row in brands], ["YETI", "Owala"])
        packet = json.loads(model.call_args.args[1])
        self.assertEqual(packet["minimum_sources_per_brand"], 1)
        self.assertIn("best overall cup", packet["sources"][0]["description"])
        self.assertIn("top pick", packet["sources"][1]["description"])
        self.assertIn("json_schema", model.call_args.kwargs)

    def test_brand_prompt_uses_dynamic_source_minimum(self):
        with open(
            tools.resource_path("prompts/casper_shopping_brand_evidence.txt"),
            "r",
            encoding="utf-8",
        ) as file:
            prompt = file.read()
        self.assertIn("minimum_sources_per_brand", prompt)
        self.assertNotIn("Cite at least two distinct publisher domains", prompt)

    def test_recommendation_controller_stops_before_merchant_pages(self):
        plan = {
            "topic": "cup",
            "search_queries": ["best cup recommendations United States"],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "USER_EXPLICIT",
            "target_count": 3,
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
                }
            ],
        }
        page = {
            "success": True,
            "content": "Our best overall cup is the YETI Rambler.",
        }
        model_result = {
            "items": [
                {
                    "title": "YETI Rambler",
                    "brand": "YETI",
                    "summary": "Independent best overall recommendation.",
                    "source_indexes": [1],
                    "verification_queries": ["YETI Rambler cup specifications"],
                }
            ],
            "reply": "推荐 YETI Rambler；它获得独立评测支持。",
        }
        fake_cards = type(
            "Cards", (), {"clean_cards": staticmethod(lambda values: values)}
        )
        fake_region = type(
            "Region", (), {"detect_shopping_region": staticmethod(lambda: self.REGION)}
        )
        fake_location = type(
            "Location", (), {"detect_location": staticmethod(lambda: self.REGION)}
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
        ) as discover, patch.object(
            browser, "read_url", return_value=page
        ) as reader, patch.object(
            tools, "run_ai_prompt", return_value=model_result
        ), patch.dict(
            "sys.modules",
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
            "_build_ai_recommendation_recovery_queries",
            return_value=[],
        ), patch.object(
            browser,
            "_build_ai_verified_recommendation_reply",
            return_value=model_result["reply"],
        ), patch.object(
            browser, "_discover_shopping_merchants"
        ) as merchant_discovery:
            result = browser.product_recommendation_controller(
                "给我推荐三个杯子"
            )
        self.assertEqual(result["evidence_route"], "independent_recommendation_sources")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["title"], "YETI Rambler")
        self.assertEqual(discover.call_count, 1)
        reader.assert_not_called()
        merchant_discovery.assert_not_called()
        card_json = json.dumps(result["cards"], ensure_ascii=False).casefold()
        self.assertNotIn("price", card_json)
        self.assertNotIn("stock", card_json)

    def test_router_and_reply_contract_keep_recommendation_separate_from_buying(self):
        with open(
            tools.resource_path("prompts/melchior_router.txt"),
            "r",
            encoding="utf-8",
        ) as file:
            router_prompt = file.read()
        with open(tools.resource_path("main.py"), "r", encoding="utf-8") as file:
            main_source = file.read()
        self.assertIn(
            '"帮我推荐三个婴儿车" → RECOMMENDATION_RESEARCH + PRODUCT',
            router_prompt,
        )
        self.assertIn("RECOMMENDATION_RESEARCH answers what is worth choosing", router_prompt)
        self.assertIn("answers where and how it can currently be bought", router_prompt)
        self.assertIn("这里没有进入商家或商品购买页", main_source)
        self.assertIn("独立评测或推荐榜单", main_source)


if __name__ == "__main__":
    unittest.main()
