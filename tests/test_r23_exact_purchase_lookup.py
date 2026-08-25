import ast
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ExactPurchaseLookupTests(unittest.TestCase):
    def test_bare_ordinal_requires_recent_shopping_context(self):
        source = (PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_shopping_context_scope"
        )
        namespace = {"re": re}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "tools.py", "exec"), namespace)
        context_scope = namespace["_shopping_context_scope"]
        self.assertEqual(context_scope("帮我买第一个"), "NEEDS_CONTEXT")
        self.assertEqual(context_scope("第二个在哪里买"), "NEEDS_CONTEXT")

    def test_ai_resolves_first_item_to_complete_context_title(self):
        value = {
            "lookup_mode": "EXACT_PRODUCT",
            "resolved_title": "Simple Modern Classic Tumbler",
            "brand": "Simple Modern",
            "source_scope": "RECENT_CONTEXT",
            "source_phrase": "Simple Modern Classic Tumbler",
            "search_queries": [
                '"Simple Modern Classic Tumbler" buy United States'
            ],
            "reason": "The user refers to the first prior recommendation.",
        }
        fake_tools = types.SimpleNamespace(
            _shopping_context_scope=Mock(return_value="NEEDS_CONTEXT"),
            run_ai_prompt=Mock(return_value=value),
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            plan = browser._plan_exact_purchase_lookup(
                "帮我查下怎么购买第一个",
                "assistant: 1. Simple Modern Classic Tumbler\n2. Stanley Quencher",
                {"country_code": "US", "country_name": "United States"},
            )
        self.assertEqual(plan["lookup_mode"], "EXACT_PRODUCT")
        self.assertEqual(plan["resolved_title"], "Simple Modern Classic Tumbler")
        kwargs = fake_tools.run_ai_prompt.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "gemma3:12b")

    def test_ungrounded_exact_identity_is_retried_then_stopped(self):
        hallucination = {
            "lookup_mode": "EXACT_PRODUCT",
            "resolved_title": "Invented Cup Pro",
            "brand": "Invented",
            "source_scope": "RECENT_CONTEXT",
            "source_phrase": "Invented Cup Pro",
            "search_queries": ["Invented Cup Pro buy"],
            "reason": "guess",
        }
        fake_tools = types.SimpleNamespace(
            _shopping_context_scope=Mock(return_value="NEEDS_CONTEXT"),
            run_ai_prompt=Mock(side_effect=[hallucination, hallucination]),
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            plan = browser._plan_exact_purchase_lookup(
                "帮我买第一个",
                "assistant: OXO Tot Transitions Straw Cup",
                {"country_code": "US"},
            )
        self.assertEqual(plan["lookup_mode"], "UNRESOLVED_REFERENCE")
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)

    def test_exact_lookup_accepts_unknown_price_and_rejects_wrong_product(self):
        search_results = [
            {
                "title": "Simple Modern Classic Tumbler | Simple Modern",
                "description": "Shop the Simple Modern Classic Tumbler.",
                "url": "https://www.simplemodern.com/products/classic-tumbler",
                "domain": "simplemodern.com",
            },
            {
                "title": "Stanley straw topper accessory",
                "description": "Accessory only.",
                "url": "https://www.amazon.com/dp/B012345678",
                "domain": "amazon.com",
            },
        ]
        proposal = {
            "items": [
                {
                    "candidate_index": 1,
                    "claimed_identity": "Simple Modern Classic Tumbler",
                    "merchant": "Simple Modern",
                    "reason": "official store",
                },
                {
                    "candidate_index": 2,
                    "claimed_identity": "Simple Modern Classic Tumbler",
                    "merchant": "Amazon",
                    "reason": "possible listing",
                },
            ]
        }
        audit = {
            "items": [
                {
                    "candidate_id": 1,
                    "verdict": "PASS",
                    "listing_title": "Simple Modern Classic Tumbler",
                    "merchant": "Simple Modern",
                    "summary": "可以在 Simple Modern 官方商店购买。",
                    "price": "UNKNOWN",
                    "currency": "UNKNOWN",
                    "stock": "UNKNOWN",
                    "checks": [
                        {"condition": name, "status": "SUPPORTED", "reason": "snippet"}
                        for name in (
                            "EXACT_IDENTITY",
                            "REAL_PURCHASE_SOURCE",
                            "PURCHASE_ENTRY",
                        )
                    ],
                    "errors_found": [],
                    "reason": "Exact official product entry.",
                },
                {
                    "candidate_id": 2,
                    "verdict": "REJECT",
                    "listing_title": "Stanley accessory",
                    "merchant": "Amazon",
                    "summary": "不是目标商品。",
                    "price": "UNKNOWN",
                    "currency": "UNKNOWN",
                    "stock": "UNKNOWN",
                    "checks": [
                        {"condition": "EXACT_IDENTITY", "status": "CONTRADICTED", "reason": "wrong product"},
                        {"condition": "REAL_PURCHASE_SOURCE", "status": "SUPPORTED", "reason": "retailer"},
                        {"condition": "PURCHASE_ENTRY", "status": "SUPPORTED", "reason": "listing"},
                    ],
                    "errors_found": ["First stage selected an unrelated accessory."],
                    "reason": "Identity mismatch.",
                },
            ]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(side_effect=[proposal, audit]))
        fake_cards = types.SimpleNamespace(clean_cards=lambda cards: cards)
        discovery = {
            "status": "OK",
            "results": search_results,
            "ai_summaries": [{"engine": "google", "summary": "Possible sellers."}],
        }
        plan = {
            "resolved_title": "Simple Modern Classic Tumbler",
            "brand": "Simple Modern",
            "search_queries": ['"Simple Modern Classic Tumbler" buy United States'],
        }
        with patch.dict(sys.modules, {"tools": fake_tools, "result_cards": fake_cards}), patch.object(
            browser, "_search_engine_policy", return_value=("google", "bing")
        ), patch.object(browser, "discover_web", return_value=discovery):
            result = browser._exact_purchase_lookup_controller(
                "帮我查一下 Simple Modern Classic Tumbler 在哪里买",
                plan,
                {"country_code": "US"},
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["cards"][0]["metadata"]["price"], "UNKNOWN")
        self.assertEqual(result["cards"][0]["domain"], "simplemodern.com")
        self.assertIn("点击下方商品卡片", result["direct_reply"])

    def test_page_escalation_opens_each_candidate_at_most_once(self):
        proposal = {
            "items": [{
                "candidate_index": 1,
                "claimed_identity": "Simple Modern Classic Tumbler",
                "merchant": "Retailer",
                "reason": "likely listing",
            }]
        }
        needs_page = {
            "items": [{
                "candidate_id": 1,
                "verdict": "NEEDS_PAGE",
                "listing_title": "Simple Modern Classic Tumbler",
                "merchant": "Retailer",
                "summary": "需要查看页面。",
                "price": "UNKNOWN",
                "currency": "UNKNOWN",
                "stock": "UNKNOWN",
                "checks": [
                    {"condition": "EXACT_IDENTITY", "status": "MISSING", "reason": "short snippet"},
                    {"condition": "REAL_PURCHASE_SOURCE", "status": "SUPPORTED", "reason": "retailer"},
                    {"condition": "PURCHASE_ENTRY", "status": "MISSING", "reason": "short snippet"},
                ],
                "errors_found": [],
                "reason": "Open once.",
            }]
        }
        passed = {
            "items": [{
                "candidate_id": 1,
                "verdict": "PASS",
                "listing_title": "Simple Modern Classic Tumbler",
                "merchant": "Retailer",
                "summary": "页面确认是目标商品。",
                "price": "$24.99",
                "currency": "USD",
                "stock": "UNKNOWN",
                "checks": [
                    {"condition": name, "status": "SUPPORTED", "reason": "page"}
                    for name in ("EXACT_IDENTITY", "REAL_PURCHASE_SOURCE", "PURCHASE_ENTRY")
                ],
                "errors_found": [],
                "reason": "Verified after one page read.",
            }]
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[proposal, needs_page, passed])
        )
        fake_cards = types.SimpleNamespace(clean_cards=lambda cards: cards)
        discovery = {
            "status": "OK",
            "results": [{
                "title": "Classic Tumbler",
                "description": "Shop now",
                "url": "https://retailer.example/classic-tumbler",
                "domain": "retailer.example",
            }],
            "ai_summaries": [],
        }
        page_reader = Mock(return_value={
            "success": True,
            "content": "Simple Modern Classic Tumbler product page $24.99",
            "structured_product": '{"@type":"Product","name":"Simple Modern Classic Tumbler"}',
            "image_url": "",
            "final_url": "https://retailer.example/classic-tumbler",
        })
        plan = {
            "resolved_title": "Simple Modern Classic Tumbler",
            "brand": "Simple Modern",
            "search_queries": ["Simple Modern Classic Tumbler buy"],
        }
        with patch.dict(sys.modules, {"tools": fake_tools, "result_cards": fake_cards}), patch.object(
            browser, "_search_engine_policy", return_value=("google", "bing")
        ), patch.object(browser, "discover_web", return_value=discovery), patch.object(
            browser, "read_url", page_reader
        ):
            result = browser._exact_purchase_lookup_controller("where buy", plan, {"country_code": "US"})
        self.assertEqual(result["status"], "OK")
        self.assertEqual(page_reader.call_count, 1)

    def test_exact_route_runs_before_generic_shopping_plan(self):
        tree = ast.parse(Path(browser.__file__).read_text(encoding="utf-8"))
        controller = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "shopping_research_controller"
        )
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(controller)
            if isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
        ]
        self.assertLess(
            calls.index("_plan_exact_purchase_lookup"),
            calls.index("build_shopping_plan"),
        )

    def test_prompt_removes_recommendation_gates_from_exact_lookup(self):
        prompt = (PROJECT_ROOT / "prompts" / "casper_exact_purchase_audit.txt").read_text(encoding="utf-8")
        self.assertIn("Price and stock are optional evidence", prompt)
        self.assertIn("Do not require popularity", prompt)
        self.assertIn("EXACT_IDENTITY", prompt)
        self.assertIn("20 oz Classic Tumbler remains", prompt)
        self.assertIn("must not contradict EXACT_IDENTITY", prompt)

    def test_exact_name_reconciliation_keeps_unrequested_capacity_variation(self):
        audits = {
            1: {
                "verdict": "REJECT",
                "listing_title": (
                    "Simple Modern Classic Tumbler with Straw Lid | 20 Ounces"
                ),
                "checks": [
                    {
                        "condition": "EXACT_IDENTITY",
                        "status": "CONTRADICTED",
                        "reason": "20 ounces is a variation",
                    },
                    {
                        "condition": "REAL_PURCHASE_SOURCE",
                        "status": "SUPPORTED",
                        "reason": "marketplace",
                    },
                    {
                        "condition": "PURCHASE_ENTRY",
                        "status": "SUPPORTED",
                        "reason": "listing",
                    },
                ],
            }
        }
        candidates = [{
            "candidate_id": 1,
            "title": "Simple Modern Classic Tumbler with Straw Lid | 20 Ounces",
            "claimed_identity": "Simple Modern Classic Tumbler",
        }]
        result = browser._reconcile_exact_purchase_identity(
            audits,
            candidates,
            {"resolved_title": "Simple Modern Classic Tumbler"},
        )
        self.assertEqual(result[1]["verdict"], "PASS")
        exact = next(
            row for row in result[1]["checks"]
            if row["condition"] == "EXACT_IDENTITY"
        )
        self.assertEqual(exact["status"], "SUPPORTED")

    def test_identity_reconciliation_does_not_override_bad_merchant(self):
        audits = {
            1: {
                "verdict": "REJECT",
                "listing_title": "Simple Modern Classic Tumbler 24 oz",
                "checks": [
                    {"condition": "EXACT_IDENTITY", "status": "CONTRADICTED"},
                    {"condition": "REAL_PURCHASE_SOURCE", "status": "CONTRADICTED"},
                    {"condition": "PURCHASE_ENTRY", "status": "SUPPORTED"},
                ],
            }
        }
        result = browser._reconcile_exact_purchase_identity(
            audits,
            [{"candidate_id": 1, "title": "Simple Modern Classic Tumbler 24 oz"}],
            {"resolved_title": "Simple Modern Classic Tumbler"},
        )
        self.assertEqual(result[1]["verdict"], "REJECT")

    def test_research_final_response_uses_12b_when_direct_reply_is_absent(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_ai_response"
        )
        rendered = ast.unparse(function)
        self.assertIn("research_final_model", rendered)
        self.assertIn("'gemma3:12b'", rendered)
        self.assertIn("'SHOPPING_RESEARCH'", rendered)
        self.assertIn("model_name=research_final_model", rendered)
        self.assertIn("False if research_final_model else 'low'", rendered)


if __name__ == "__main__":
    unittest.main()
