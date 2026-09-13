import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import source_scope


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class LiteralSourceScopeTests(unittest.TestCase):
    def test_named_sites_are_extracted_only_when_bound_to_search(self):
        cases = {
            "请去 B 站核实成员名单，只看官方账号": (
                ["bilibili.com"], True
            ),
            "去 YouTube 搜索 aespa live clips": (["youtube.com"], False),
            "去 Wiki 查四禧丸子的背景": (["wikipedia.org"], False),
            "去 example.org 搜索 release notes": (["example.org"], False),
        }
        for message, (sites, official) in cases.items():
            with self.subTest(message=message):
                contract = source_scope.route_contract(message)
                self.assertEqual(contract["source_scope"], "FIXED_SITES")
                self.assertEqual(contract["requested_sites"], sites)
                self.assertEqual(contract["official_only"], official)

    def test_site_mention_without_source_instruction_is_not_fixed(self):
        self.assertEqual(
            source_scope.route_contract("B站是什么公司？"),
            {
                "source_scope": "OPEN_WEB",
                "requested_sites": [],
                "official_only": False,
            },
        )

    def test_subdomains_match_but_unrelated_domains_do_not(self):
        self.assertTrue(
            source_scope.domain_matches("zh.wikipedia.org", "wikipedia.org")
        )
        self.assertFalse(
            source_scope.domain_matches("fakewikipedia.org", "wikipedia.org")
        )

    def test_query_constraint_is_literal_and_bounded(self):
        self.assertEqual(
            source_scope.constrain_query("四禧丸子 成员", ["bilibili.com"]),
            "site:bilibili.com 四禧丸子 成员",
        )


class FixedSourceMelchiorTests(unittest.TestCase):
    def test_fact_purpose_bypasses_social_and_second_router(self):
        from tests.test_stable_v1_magi import _load_melchior

        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=AssertionError("fixed fact route must be authoritative"),
        ):
            plan = module.plan_request(
                "请去B站核实四禧丸子当前成员，只看官方账号",
                magi_route={
                    "lane": "SEARCH",
                    "confidence": 0.95,
                    "search_scope": "FACT_LOOKUP",
                    "social_scope": "OTHER",
                    "social_platforms": [],
                    "source_scope": "FIXED_SITES",
                    "requested_sites": ["bilibili.com"],
                    "official_only": True,
                },
            )
        self.assertEqual(plan["response_mode"], "FACT_LOOKUP")
        self.assertEqual(plan["source_policy"], "fixed_official_sites")
        self.assertEqual(plan["requested_sites"], ["bilibili.com"])
        self.assertTrue(plan["official_only"])
        self.assertEqual(plan["social_platforms"], [])


class FixedSourceCasperTests(unittest.TestCase):
    def test_safety_rejects_malformed_or_widened_source_contracts(self):
        from casper import safety

        valid = {
            "response_mode": "FACT_LOOKUP",
            "source_scope": "FIXED_SITES",
            "requested_sites": ["bilibili.com"],
            "official_only": True,
        }
        self.assertTrue(safety.validate_plan(valid)["allowed"])
        malformed = dict(valid, requested_sites=["bilibili.com", {}])
        self.assertFalse(safety.validate_plan(malformed)["allowed"])
        widened = dict(valid, source_scope="OPEN_WEB")
        self.assertFalse(safety.validate_plan(widened)["allowed"])

    def test_fact_adapter_passes_fixed_source_to_browser(self):
        from casper import adapters
        from casper import browser

        tools_stub = types.SimpleNamespace(
            unload_model=lambda *_a, **_k: None,
            build_search_query=lambda *_a, **_k: "四禧丸子 当前成员",
        )
        with patch.dict(sys.modules, {"tools": tools_stub}), patch.object(
            browser,
            "fact_lookup_controller",
            return_value={"status": "NO_RESULTS", "results": []},
        ) as controller:
            adapters.execute_mode(
                "请去B站核实四禧丸子当前成员，只看官方账号",
                {
                    "response_mode": "FACT_LOOKUP",
                    "risk": "low",
                    "source_scope": "FIXED_SITES",
                    "requested_sites": ["bilibili.com"],
                    "official_only": True,
                },
                {},
                "",
                lambda *_a: None,
            )
        self.assertEqual(
            controller.call_args.kwargs["requested_sites"], ["bilibili.com"]
        )
        self.assertTrue(controller.call_args.kwargs["official_only"])

    def test_official_claim_uses_page_validating_fact_browser(self):
        from casper import adapters
        from casper import browser

        tools_stub = types.SimpleNamespace(
            unload_model=lambda *_a, **_k: None,
            build_claim_query=lambda *_a, **_k: "四禧丸子 已换成员",
        )
        with patch.dict(sys.modules, {"tools": tools_stub}), patch.object(
            browser,
            "fact_lookup_controller",
            return_value={"status": "NO_RESULTS", "results": []},
        ) as controller:
            adapters.execute_mode(
                "请去B站官方账号核实四禧丸子是否换了成员",
                {
                    "response_mode": "CLAIM_CHECK",
                    "risk": "low",
                    "claim_to_verify": "四禧丸子已换成员",
                    "source_scope": "FIXED_SITES",
                    "requested_sites": ["bilibili.com"],
                    "official_only": True,
                },
                {},
                "",
                lambda *_a: None,
            )
        self.assertEqual(
            controller.call_args.kwargs["requested_sites"], ["bilibili.com"]
        )
        self.assertTrue(controller.call_args.kwargs["official_only"])

    def test_official_social_search_stops_when_identity_cannot_be_proved(self):
        from casper import adapters

        tools_stub = types.SimpleNamespace(unload_model=lambda *_a, **_k: None)
        with patch.dict(sys.modules, {"tools": tools_stub}):
            result, _context = adapters.execute_mode(
                "只总结B站官方账号的帖子",
                {
                    "response_mode": "SOCIAL_RESEARCH",
                    "risk": "low",
                    "social_platforms": ["bilibili"],
                    "source_scope": "FIXED_SITES",
                    "requested_sites": ["bilibili.com"],
                    "official_only": True,
                },
                {},
                "",
                lambda *_a: None,
            )
        self.assertEqual(result["status"], "SOURCE_SCOPE_UNSUPPORTED")

    def test_fact_browser_filters_discovery_and_skips_external_fallback(self):
        from casper import browser

        fact_scope = {"temporal_scope": "CURRENT"}
        entity_scope = {"included_scope": "四禧丸子"}
        audit = {"approved_search_query": "四禧丸子 当前成员"}
        tools_stub = types.SimpleNamespace()
        with patch.dict(sys.modules, {"tools": tools_stub}), patch.object(
            browser, "_plan_fact_intent_scope", return_value=fact_scope
        ), patch.object(
            browser, "_plan_fact_entity_scope", return_value=entity_scope
        ), patch.object(
            browser, "_audit_fact_search_query", return_value=audit
        ), patch.object(
            browser, "_discover_native_fixed_fact_candidates", return_value=None
        ), patch.object(
            browser,
            "discover_web",
            return_value={"status": "NO_RESULTS", "results": []},
        ) as discovery:
            result = browser.fact_lookup_controller(
                "四禧丸子 当前成员",
                user_request="请去B站核实，只看官方账号",
                requested_sites=["bilibili.com"],
                official_only=True,
            )
        self.assertEqual(
            discovery.call_args.args[0],
            "site:bilibili.com 四禧丸子 当前成员",
        )
        self.assertEqual(
            discovery.call_args.kwargs["allowed_domains"], ["bilibili.com"]
        )
        self.assertEqual(
            result["external_ai_fallback"]["reason"], "fixed_source_scope"
        )
        self.assertEqual(
            result["source_contract"]["requested_sites"], ["bilibili.com"]
        )


class FixedSourcePackagingTests(unittest.TestCase):
    def test_build_and_installer_include_source_contract(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        installer = (ROOT / "INSTALL_STABLE_V1.ps1").read_text(encoding="utf-8")
        self.assertIn('"source_scope.py"', installer)


if __name__ == "__main__":
    unittest.main()
