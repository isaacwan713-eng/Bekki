import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from casper import browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VerifiedRecommendationTests(unittest.TestCase):
    def test_ai_verdict_rejects_wrong_category_and_keeps_supported_match(self):
        candidates = [
            {
                "candidate_id": 1,
                "title": "Actual Straw Tumbler",
                "brand": "Example",
                "summary": "Initial recommendation",
                "url": "https://review.example/a",
                "domain": "review.example",
                "source_count": 1,
                "source_domains": ["review.example"],
                "verification_queries": ["Actual Straw Tumbler specs"],
                "required_check_count": 2,
                "verification_sources": [
                    {
                        "index": 1,
                        "domain": "maker.example",
                        "title": "Actual Straw Tumbler specifications",
                        "description": "Stainless steel tumbler with a straw.",
                        "url": "https://maker.example/a",
                    }
                ],
            },
            {
                "candidate_id": 2,
                "title": "Soft Spout Trainer",
                "brand": "Example",
                "summary": "Initial recommendation",
                "url": "https://review.example/b",
                "domain": "review.example",
                "source_count": 1,
                "source_domains": ["review.example"],
                "verification_queries": ["Soft Spout Trainer specs"],
                "required_check_count": 2,
                "verification_sources": [
                    {
                        "index": 1,
                        "domain": "maker.example",
                        "title": "Soft Spout Trainer specifications",
                        "description": "A toddler trainer with a soft spout.",
                        "url": "https://maker.example/b",
                    }
                ],
            },
        ]
        raw = {
            "items": [
                {
                    "candidate_id": 1,
                    "verdict": "PASS",
                    "summary": "证据确认它是不锈钢吸管杯。",
                    "source_indexes": [1],
                    "checks": [
                        {"condition": "category", "status": "SUPPORTED"},
                        {"condition": "audience", "status": "SUPPORTED"},
                    ],
                    "failed_conditions": [],
                },
                {
                    "candidate_id": 2,
                    "verdict": "FAIL",
                    "summary": "这是软嘴训练杯，证据没有显示吸管。",
                    "source_indexes": [1],
                    "checks": [
                        {"condition": "category", "status": "CONTRADICTED"},
                        {"condition": "audience", "status": "CONTRADICTED"},
                    ],
                    "failed_conditions": ["straw cup"],
                },
            ]
        }
        passed, rejected = browser._accept_ai_recommendation_verdicts(
            raw, candidates
        )
        self.assertEqual([item["title"] for item in passed], ["Actual Straw Tumbler"])
        self.assertEqual([item["title"] for item in rejected], ["Soft Spout Trainer"])
        self.assertEqual(passed[0]["verification_source_count"], 1)

    def test_candidate_follow_up_does_not_open_known_merchant_product_page(self):
        discovery = {
            "status": "OK",
            "results": [
                {
                    "domain": "amazon.com",
                    "title": "Buy Example Cup",
                    "description": "Product page",
                    "url": "https://amazon.com/dp/ABC123",
                },
                {
                    "domain": "maker.example",
                    "title": "Example Cup specifications",
                    "description": "A tumbler with a removable straw.",
                    "url": "https://maker.example/example-cup",
                },
            ],
        }
        option = {
            "verification_queries": ["Example Cup straw specifications"]
        }
        with patch.object(
            browser, "discover_web", return_value=discovery
        ), patch.object(
            browser,
            "read_url",
            return_value={"success": True, "content": "Uses a drinking straw."},
        ) as read:
            sources = browser._candidate_verification_sources(
                option,
                {"country_code": "US"},
                ("google", "bing"),
            )
        self.assertEqual([item["domain"] for item in sources], ["maker.example"])
        read.assert_not_called()

    def test_page_escalation_opens_at_most_one_candidate_source(self):
        candidate = {
            "candidate_id": 1,
            "verification_sources": [
                {
                    "index": 1,
                    "domain": "one.example",
                    "description": "Short snippet.",
                    "url": "https://one.example/item",
                },
                {
                    "index": 2,
                    "domain": "two.example",
                    "description": "Another snippet.",
                    "url": "https://two.example/item",
                },
            ],
        }
        with patch.object(
            browser,
            "read_url",
            return_value={"success": True, "content": "Full evidence."},
        ) as read:
            result = browser._enrich_candidate_verification_sources(candidate)
        self.assertEqual(read.call_count, 1)
        self.assertTrue(result["page_escalated"])
        self.assertTrue(result["verification_sources"][0]["page_read"])
        self.assertNotIn("page_read", result["verification_sources"][1])

    def test_structural_audit_rejects_contradicted_audience_even_if_ai_says_pass(self):
        candidate = {
            "candidate_id": 1,
            "title": "Toddler Cup",
            "brand": "Example",
            "required_check_count": 2,
            "verification_sources": [
                {
                    "index": 1,
                    "domain": "maker.example",
                    "url": "https://maker.example/toddler",
                }
            ],
        }
        raw = {
            "items": [
                {
                    "candidate_id": 1,
                    "verdict": "PASS",
                    "summary": "Actually made only for toddlers.",
                    "source_indexes": [1],
                    "checks": [
                        {"condition": "category", "status": "SUPPORTED"},
                        {"condition": "audience", "status": "CONTRADICTED"},
                    ],
                    "failed_conditions": ["audience"],
                }
            ]
        }
        passed, rejected = browser._accept_ai_recommendation_verdicts(
            raw, [candidate]
        )
        self.assertEqual(passed, [])
        self.assertEqual(rejected[0]["verdict"], "FAIL")

    def test_recommendation_prompts_require_verification_and_recovery(self):
        verify = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_verify.txt"
        ).read_text(encoding="utf-8")
        recovery = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_recovery.txt"
        ).read_text(encoding="utf-8")
        options = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_options.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("soft-spout trainer cup", verify)
        self.assertIn("verification_queries", options)
        self.assertIn("too few verified candidates", recovery)

    def test_authoritative_router_uses_4b_primary_and_12b_recovery(self):
        tree = ast.parse((PROJECT_ROOT / "melchior.py").read_text(encoding="utf-8"))
        planner = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "plan_request"
        )
        rendered = ast.unparse(planner)
        self.assertGreaterEqual(
            rendered.count("model_name='gemma3:4b'"),
            1,
        )
        self.assertGreaterEqual(rendered.count("model_name='gemma3:12b'"), 1)
        self.assertNotIn("model_name='gpt-oss:20b'", rendered)


if __name__ == "__main__":
    unittest.main()
