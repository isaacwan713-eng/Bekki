import ast
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import browser


class SummaryFirstTests(unittest.TestCase):
    def test_google_ai_overview_extraction_supports_english_and_chinese(self):
        english = "Header\nAI Overview\nAnswer one.\nAnswer two.\nSources\nSite"
        chinese = "页首\nAI 概览\n这是总结。\n来源\n网站"
        self.assertEqual(
            browser._extract_google_ai_summary(english),
            "Answer one. Answer two.",
        )
        self.assertEqual(
            browser._extract_google_ai_summary(chinese),
            "这是总结。",
        )

    def test_missing_audit_check_escalates_then_becomes_unverified(self):
        base = {
            "candidate_id": 1,
            "title": "Example Cup",
            "brand": "Example",
            "required_check_count": 2,
            "verification_sources": [
                {
                    "index": 1,
                    "domain": "example.com",
                    "url": "https://example.com/cup",
                }
            ],
        }
        raw = {
            "items": [
                {
                    "candidate_id": 1,
                    "verdict": "PASS",
                    "summary": "Only category was established.",
                    "source_indexes": [1],
                    "checks": [
                        {"condition": "category", "status": "SUPPORTED"}
                    ],
                    "failed_conditions": ["audience"],
                }
            ]
        }
        _passed, rejected = browser._accept_ai_recommendation_verdicts(
            raw, [base]
        )
        self.assertEqual(rejected[0]["verdict"], "NEEDS_PAGE")
        escalated = dict(base)
        escalated["page_escalated"] = True
        _passed, rejected = browser._accept_ai_recommendation_verdicts(
            raw, [escalated]
        )
        self.assertEqual(rejected[0]["verdict"], "UNVERIFIED")

    def test_fact_summary_fast_path_requires_independent_audit(self):
        discovery = {
            "status": "OK",
            "ai_summaries": [
                {"engine": "google", "summary": "Initial overview."}
            ],
            "results": [
                {
                    "title": "Source A",
                    "description": "The current value is 42.",
                    "domain": "a.example",
                    "url": "https://a.example/value",
                },
                {
                    "title": "Source B",
                    "description": "The current value is 42.",
                    "domain": "b.example",
                    "url": "https://b.example/value",
                },
            ],
        }
        proposal = {
            "answer": "答案是 41。",
            "claims": ["答案是 41"],
            "source_indexes": [1],
            "uncertainties": [],
        }
        audit = {
            "verdict": "ACCEPT",
            "answer": "答案是 42。",
            "source_indexes": [1, 2],
            "checks": [
                {"condition": name, "status": "SUPPORTED"}
                for name in (
                    "DIRECTLY_ANSWERS",
                    "TIME_SCOPE_SUPPORTED",
                    "SOURCE_AGREEMENT",
                    "NO_CONTRADICTION",
                )
            ],
            "errors_found": ["第一阶段把 42 写成了 41。"],
            "reason": "Two snippets agree.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[proposal, audit])
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._try_search_summary_fact_answer(
                "current value",
                "现在是多少？",
                {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "requested_period": "current",
                    "allow_previous_period": False,
                    "reason": "current request",
                },
                discovery,
            )
        self.assertEqual(result["answer"], "答案是 42。")
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)

    def test_recommendation_controller_has_no_default_page_enrichment(self):
        tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
        controller = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "product_recommendation_controller"
        )
        rendered = ast.unparse(controller)
        self.assertNotIn("_enrich_recommendation_sources", rendered)

    def test_high_risk_fact_path_bypasses_summary_fast_path(self):
        tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
        controller = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "fact_lookup_controller"
        )
        rendered = ast.unparse(controller)
        self.assertIn("risk", rendered)
        self.assertIn("!= 'high'", rendered)
        self.assertIn("_try_search_summary_fact_answer", rendered)

    def test_fact_research_helpers_use_12b_not_20b(self):
        tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
        functions = {
            node.name: ast.unparse(node)
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in (
            "_plan_fact_intent_scope",
            "_plan_fact_entity_scope",
            "_certify_fact_search_query",
            "_audit_fact_search_query",
            "_try_search_summary_fact_answer",
            "_validate_candidate_answer",
            "_validate_temporal_scope",
            "_audit_combined_fact_resolution",
            "_resolve_combined_fact",
            "_plan_evidence_gap",
        ):
            with self.subTest(name=name):
                self.assertIn("model_name='gemma4:12b'", functions[name])
                self.assertNotIn("model_name='gpt-oss:20b'", functions[name])


if __name__ == "__main__":
    unittest.main()
