import json
import unittest
from unittest.mock import Mock, patch

import tools
from casper import browser


class CompactJsonTests(unittest.TestCase):
    def test_call_model_forwards_json_schema_to_ollama(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        with patch.object(
            tools.model_runtime, "generate", return_value='{"ok":true}'
        ) as generate:
            tools.call_model("x", response_format=schema)
        self.assertEqual(generate.call_args.kwargs["response_format"], schema)


class RecommendationFirstTests(unittest.TestCase):
    REGION = {"country_code": "US", "country_name": "United States"}

    @staticmethod
    def sources():
        return [
            {
                "index": 1,
                "domain": "review-a.example",
                "title": "Best cups of 2026",
                "description": "YETI is a popular cup brand with 2,000 customer reviews.",
                "url": "https://review-a.example/cups",
                "published": "2026-07-01",
            },
            {
                "index": 2,
                "domain": "review-b.example",
                "title": "Expert cup recommendations",
                "description": "Our highly reviewed YETI cup pick remains a best seller.",
                "url": "https://review-b.example/cups",
                "published": "2026-06-01",
            },
        ]

    def test_compact_brand_indexes_are_grounded_by_python(self):
        result = {"brands": [{"name": "YETI", "source_indexes": [1, 2]}]}
        brands = browser._validate_brand_evidence(
            result, self.sources(), 2, "NONE", "cup"
        )
        self.assertEqual([item["name"] for item in brands], ["YETI"])
        self.assertEqual(brands[0]["source_count"], 2)
        self.assertTrue(all(row["support"] for row in brands[0]["evidence"]))

    def test_unrelated_generic_brand_list_is_rejected(self):
        sources = self.sources()
        for source in sources:
            source["title"] = "Most popular household brands"
            source["description"] = "Dyson is a popular vacuum brand with 2,000 reviews."
        result = {"brands": [{"name": "Dyson", "source_indexes": [1, 2]}]}
        self.assertEqual(
            browser._validate_brand_evidence(result, sources, 2, "NONE", "cup"),
            [],
        )

    def test_generic_discovery_searches_recommendations_first(self):
        discovery = {"status": "OK", "results": []}
        with patch.object(browser, "discover_web", return_value=discovery) as search:
            brands = browser._discover_popular_brands(
                "给我推荐三个杯子",
                {"product_query": "cup", "popularity_requirement": "NONE"},
                self.REGION,
                ("google", "bing"),
            )
        self.assertEqual(brands, [])
        query = search.call_args.args[0].casefold()
        self.assertIn("best recommendations", query)
        self.assertIn("expert reviews", query)
        self.assertIn("comparison roundup", query)
        self.assertIn("united states", query)

    def test_merchant_model_returns_indexes_only(self):
        discovery = {
            "status": "OK",
            "results": [
                {
                    "domain": "amazon.com",
                    "title": "Amazon Cups Store",
                    "description": "Shop cups and add to cart.",
                    "url": "https://amazon.com/s?k=cups",
                },
                {
                    "domain": "example.com",
                    "title": "Cup review roundup",
                    "description": "Editorial buying guide.",
                    "url": "https://example.com/reviews",
                },
            ],
        }
        with patch.object(browser, "discover_web", return_value=discovery), patch.object(
            tools, "run_ai_prompt", return_value={"source_indexes": [1]}
        ) as model:
            result = browser._discover_shopping_merchants(
                "给我推荐三个杯子",
                {"product_query": "cup", "queries": ["best cup recommendations"]},
                self.REGION,
                engine_plan=("google", "bing"),
            )
        self.assertEqual([row["domain"] for row in result["merchants"]], ["amazon.com"])
        packet = json.loads(model.call_args.args[1])
        self.assertNotIn("url", packet["discovered_sources"][0])
        self.assertEqual(model.call_args.kwargs["num_predict"], 160)
        self.assertIn("json_schema", model.call_args.kwargs)

    def test_generic_selection_rejects_bulk_and_unavailable_products(self):
        evidence = [{"name": "Acme", "source_count": 2, "source_domains": ["a", "b"]}]
        plan = {
            "popularity_requirement": "NONE",
            "verified_brand_evidence": evidence,
            "requirements": [],
        }
        base = {
            "page_type": "PRODUCT",
            "is_product_detail_url": True,
            "brand": "Acme",
            "popularity_status": "HIGH",
            "popularity_evidence": "2,000 reviews",
            "evidence_quality": "HIGH",
            "fit_score": 90,
        }
        bulk = {**base, "product_title": "Acme 100 Count Disposable Plastic Cups"}
        unavailable = {**base, "product_title": "Acme Everyday Cup", "stock": "Out of stock"}
        normal = {**base, "product_title": "Acme Reusable Everyday Cup", "stock": "In stock"}
        self.assertEqual(
            browser._select_shopping_products(
                "给我推荐三个杯子", plan, [bulk, unavailable, normal]
            ),
            [3],
        )
        self.assertEqual(
            browser._select_shopping_products("推荐一次性杯子", plan, [bulk]),
            [1],
        )


if __name__ == "__main__":
    unittest.main()
