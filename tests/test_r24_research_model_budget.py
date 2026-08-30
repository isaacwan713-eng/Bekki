import ast
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import browser, core


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def function_source(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return ast.unparse(node), node


class ResearchModelBudgetTests(unittest.TestCase):
    def test_recent_months_resolve_to_bounded_current_window(self):
        _source, function = function_source(
            PROJECT_ROOT / "tools.py", "_resolved_news_window"
        )
        namespace = {"datetime": datetime, "timedelta": timedelta, "re": re}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "tools.py", "exec"),
            namespace,
        )
        start, end = namespace["_resolved_news_window"](
            "SNH48这几个月有什么新闻吗？",
            today=date(2026, 8, 27),
        )
        self.assertEqual(end, date(2026, 8, 27))
        self.assertEqual(start, date(2026, 4, 25))

    def test_news_query_discards_model_generated_stale_year_window(self):
        tools_tree = ast.parse(
            (PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")
        )
        functions = [
            node for node in tools_tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_resolved_news_window", "build_news_queries"}
        ]

        class FixedDateTime:
            @classmethod
            def now(cls):
                return datetime(2026, 8, 27, 12, 0, 0)

        namespace = {
            "datetime": FixedDateTime,
            "timedelta": timedelta,
            "re": re,
            "json": json,
            "run_ai_prompt": lambda *_args, **_kwargs: {
                "queries": [
                    "SNH48 news August 2023 - August 2026",
                    "SNH48 official announcements 2023-2026",
                ]
            },
        }
        exec(
            compile(ast.Module(body=functions, type_ignores=[]), "tools.py", "exec"),
            namespace,
        )
        queries = namespace["build_news_queries"](
            "SNH48这几个月有什么新闻吗？"
        )
        self.assertEqual(len(queries), 2)
        self.assertTrue(all("2023" not in query for query in queries))
        self.assertTrue(all("2026-04-25" in query for query in queries))
        self.assertTrue(all("2026-08-27" in query for query in queries))

    def test_fact_scope_prompts_classify_yesterday_as_explicit_period(self):
        prompt_root = PROJECT_ROOT / "prompts"
        for name in ("fact_intent_scope.txt", "fact_intent_scope_retry.txt"):
            text = (prompt_root / name).read_text(encoding="utf-8")
            self.assertIn("EXPLICIT_PERIOD", text)
            self.assertIn("Yesterday", text.replace("yesterday", "Yesterday"))

    def test_fact_scope_reconciles_yesterday_schema_contradiction(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value={
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "Yesterday's game",
                "allow_previous_period": False,
                "reason": "specific past day",
            })
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_intent_scope(
                "道奇昨天赢了吗",
                "Los Angeles Dodgers August 19 final score",
            )
        self.assertEqual(result["scope_type"], "EXPLICIT_PERIOD")

    def test_current_fact_scope_completes_null_period_and_uses_schema(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value={
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": None,
                "allow_previous_period": False,
                "reason": "current organization structure",
            })
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_intent_scope(
                "SNH48现在有哪些正式分队？",
                "SNH48 official teams 2026",
            )
        self.assertEqual(result["scope_type"], "CURRENT_ACTIVE_STATE")
        self.assertIn("current active state as of", result["requested_period"])
        schema = fake_tools.run_ai_prompt.call_args.kwargs["json_schema"]
        self.assertEqual(
            schema["properties"]["scope_type"]["enum"],
            [
                "CURRENT_ACTIVE_STATE",
                "LATEST_COMPLETED_PERIOD",
                "EXPLICIT_PERIOD",
            ],
        )

    def test_current_fact_scope_cannot_allow_previous_period(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value={
                "scope_type": "CURRENT_ACTIVE_STATE",
                "requested_period": "current active state as of 2026-08-28",
                "allow_previous_period": True,
                "reason": "current official team structure",
            })
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_intent_scope(
                "SNH48现在有哪些正式分队？",
                "SNH48 official current teams 2026",
            )
        self.assertIs(result["allow_previous_period"], False)

    def test_fact_entity_scope_is_owned_by_ai_semantic_contract(self):
        planned = {
            "target_entity": "Example organization",
            "requested_relation": "internal operating divisions",
            "required_facets": ["division list", "assignment mechanism"],
            "included_scope": "internal divisions of the named organization",
            "excluded_adjacent_scopes": ["affiliated organizations"],
            "source_language_boundaries": [],
            "reason": "The user asked about internal structure.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value=planned)
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_entity_scope(
                "What are the organization's internal divisions?",
                "organization groups",
            )
        self.assertEqual(result["target_entity"], "Example organization")
        self.assertEqual(result["required_facets"], planned["required_facets"])
        schema = fake_tools.run_ai_prompt.call_args.kwargs["json_schema"]
        self.assertIn("excluded_adjacent_scopes", schema["required"])
        self.assertIn("source_language_boundaries", schema["required"])

        source, _node = function_source(
            PROJECT_ROOT / "casper" / "browser.py",
            "_plan_fact_entity_scope",
        )
        for domain_literal in ("SNH48", "分队", "GNZ48"):
            self.assertNotIn(domain_literal, source)

    def test_open_source_expression_requires_preservation_policy(self):
        invalid = {
            "target_entity": "Example organization",
            "requested_relation": "meaning of the source taxonomy",
            "required_facets": ["source taxonomy meaning"],
            "included_scope": "the unresolved source expression",
            "excluded_adjacent_scopes": ["a neighboring status"],
            "source_language_boundaries": [{
                "source_expression": "原词",
                "established_equivalent": "neighboring status",
                "meaning_status": "OPEN_RESEARCH_TARGET",
                "translation_policy": "EXACT_EQUIVALENT_ALLOWED",
                "boundary_reason": "USER_PROVIDED_EXACT_EQUIVALENT",
                "excluded_conflations": ["neighboring status"],
            }],
            "reason": "The term's meaning is the research target.",
        }
        repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
        repaired["source_language_boundaries"][0][
            "translation_policy"
        ] = "PRESERVE_SOURCE_EXPRESSION"
        repaired["source_language_boundaries"][0][
            "established_equivalent"
        ] = None
        repaired["source_language_boundaries"][0][
            "boundary_reason"
        ] = "MEANING_OR_RELATION_IS_RESEARCH_TARGET"
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[invalid, repaired])
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._plan_fact_entity_scope(
                "原词是什么意思？",
                "neighboring status meaning",
            )
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)
        boundary = result["source_language_boundaries"][0]
        self.assertEqual(boundary["meaning_status"], "OPEN_RESEARCH_TARGET")
        self.assertEqual(
            boundary["translation_policy"],
            "PRESERVE_SOURCE_EXPRESSION",
        )

    def test_fact_scope_prompts_protect_open_source_taxonomy_questions(self):
        paths = [
            PROJECT_ROOT / "prompts" / "search_query.txt",
            PROJECT_ROOT / "prompts" / "fact_entity_scope.txt",
            PROJECT_ROOT / "prompts" / "fact_query_scope_audit.txt",
            PROJECT_ROOT / "prompts" / "fact_query_scope_certify.txt",
            PROJECT_ROOT / "prompts" / "fact_query_scope_audit_focused.txt",
            PROJECT_ROOT / "prompts" / "fact_query_scope_certify_focused.txt",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8").casefold()
            self.assertIn("source", text, path.name)
            self.assertTrue(
                "unestablished" in text
                or "unverified" in text
                or "no safely exact equivalent" in text,
                path.name,
            )
        entity_prompt = (
            PROJECT_ROOT / "prompts" / "fact_entity_scope.txt"
        ).read_text(encoding="utf-8").casefold()
        self.assertTrue(
            "mixed-language" in entity_prompt
            or "mix languages" in entity_prompt
        )

    def test_fact_search_query_scope_is_rewritten_by_ai_not_keywords(self):
        audited = {
            "decision": "REWRITE",
            "proposed_query_scope_match": False,
            "approved_query_scope_match": True,
            "approved_search_query": (
                "Example organization internal divisions official current"
            ),
            "source_language_boundaries_respected": True,
            "reason": "The draft broadened the requested hierarchy.",
        }
        certified = {
            "accepted": True,
            "literal_scope_paraphrase": (
                "The organization's internal divisions."
            ),
            "strongest_adjacent_interpretation": (
                "Affiliated organizations, defeated by the internal relation."
            ),
            "adjacent_interpretation_plausible": False,
            "hierarchy_boundary_explicit": True,
            "exact_entity_scope": True,
            "all_facets_preserved": True,
            "translation_boundary_clear": True,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": True,
            "reason": "The literal query exposes the requested hierarchy.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[audited, certified])
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._audit_fact_search_query(
                "What are its internal divisions?",
                "Example organization groups",
                {
                    "target_entity": "Example organization",
                    "requested_relation": "internal divisions",
                    "required_facets": ["division list"],
                    "included_scope": "internal divisions",
                    "excluded_adjacent_scopes": ["affiliates"],
                },
            )
        self.assertEqual(result["decision"], "REWRITE")
        self.assertEqual(
            result["approved_search_query"],
            audited["approved_search_query"],
        )
        self.assertIs(result["certification"]["accepted"], True)
        payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[0].args[1]
        )
        self.assertEqual(
            payload["original_user_message"],
            "What are its internal divisions?",
        )

        source, _node = function_source(
            PROJECT_ROOT / "casper" / "browser.py",
            "_audit_fact_search_query",
        )
        for domain_literal in ("SNH48", "分队", "group"):
            self.assertNotIn(domain_literal, source)

    def test_independent_ai_repairs_semantically_ambiguous_literal_query(self):
        first_audit = {
            "decision": "REWRITE",
            "proposed_query_scope_match": False,
            "approved_query_scope_match": True,
            "approved_search_query": "Example organization sub-groups",
            "source_language_boundaries_respected": True,
            "reason": "The query names the requested organization.",
        }
        rejected_certification = {
            "accepted": False,
            "literal_scope_paraphrase": (
                "The organization's broadly described sub-groups."
            ),
            "strongest_adjacent_interpretation": (
                "Affiliated organizations could also be sub-groups."
            ),
            "adjacent_interpretation_plausible": True,
            "hierarchy_boundary_explicit": False,
            "exact_entity_scope": False,
            "all_facets_preserved": True,
            "translation_boundary_clear": False,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": False,
            "reason": "The literal can include affiliated organizations.",
        }
        repaired_audit = {
            "decision": "REWRITE",
            "proposed_query_scope_match": False,
            "approved_query_scope_match": True,
            "approved_search_query": (
                "Example organization internal operating divisions, "
                "excluding affiliated organizations"
            ),
            "source_language_boundaries_respected": True,
            "reason": "The standalone query now exposes the boundary.",
        }
        accepted_certification = {
            "accepted": True,
            "literal_scope_paraphrase": (
                "Internal operating divisions, excluding affiliates."
            ),
            "strongest_adjacent_interpretation": (
                "Affiliates are explicitly excluded by the literal query."
            ),
            "adjacent_interpretation_plausible": False,
            "hierarchy_boundary_explicit": True,
            "exact_entity_scope": True,
            "all_facets_preserved": True,
            "translation_boundary_clear": True,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": True,
            "reason": "The literal query is independently unambiguous.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(
                side_effect=[
                    first_audit,
                    rejected_certification,
                    repaired_audit,
                    accepted_certification,
                ]
            )
        )
        entity_scope = {
            "target_entity": "Example organization",
            "requested_relation": "internal operating divisions",
            "required_facets": ["division list"],
            "included_scope": "internal operating divisions",
            "excluded_adjacent_scopes": ["affiliated organizations"],
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._audit_fact_search_query(
                "What are its internal operating divisions?",
                "Example organization affiliated groups",
                entity_scope,
            )

        self.assertEqual(
            result["approved_search_query"],
            repaired_audit["approved_search_query"],
        )
        self.assertIs(result["certification"]["accepted"], True)
        prompts = [
            call.args[0]
            for call in fake_tools.run_ai_prompt.call_args_list
        ]
        self.assertEqual(
            prompts,
            [
                "prompts/fact_query_scope_audit.txt",
                "prompts/fact_query_scope_certify.txt",
                "prompts/fact_query_scope_audit_retry.txt",
                "prompts/fact_query_scope_certify.txt",
            ],
        )
        repair_payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[2].args[1]
        )
        self.assertEqual(
            repair_payload["independent_certification_failure"],
            rejected_certification,
        )

        source, _node = function_source(
            PROJECT_ROOT / "casper" / "browser.py",
            "_certify_fact_search_query",
        )
        for domain_literal in ("SNH48", "分队", "GNZ48"):
            self.assertNotIn(domain_literal, source)

        certifier_prompt = (
            PROJECT_ROOT / "prompts" / "fact_query_scope_certify.txt"
        ).read_text(encoding="utf-8")
        retry_prompt = (
            PROJECT_ROOT / "prompts" / "fact_query_scope_audit_retry.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("not whether a search engine can guarantee", certifier_prompt)
        self.assertIn("Parentheses do not weaken", certifier_prompt)
        self.assertIn("normal reader", certifier_prompt)
        self.assertNotIn('"accepted":false', certifier_prompt)
        self.assertIn("both the intended entity relationship", retry_prompt)

    def test_fact_query_scope_keeps_two_ai_roles_without_third_arbiter(self):
        source = (PROJECT_ROOT / "casper" / "browser.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("fact_query_scope_disagreement_arbiter", source)
        self.assertNotIn("_arbitrate_primary_fact_query", source)
        self.assertFalse(
            (
                PROJECT_ROOT
                / "prompts"
                / "fact_query_scope_disagreement_arbiter.txt"
            ).exists()
        )

    def test_focused_follow_up_query_is_judged_as_part_of_query_set(self):
        focused_query = "Example organization official cohort 9 members"
        sibling_query = "Example organization official division schedule"
        audited = {
            "decision": "USE",
            "proposed_query_scope_match": True,
            "approved_query_scope_match": True,
            "approved_search_query": focused_query,
            "source_language_boundaries_respected": True,
            "focused_facet": "official cohort members",
            "proposed_focused_facet_preserved": True,
            "approved_focused_facet_preserved": True,
            "query_set_collectively_covers_gaps": True,
            "reason": "This query intentionally targets one missing facet.",
        }
        certified = {
            "accepted": True,
            "literal_scope_paraphrase": "Official cohort 9 members.",
            "strongest_adjacent_interpretation": (
                "A training status, defeated by preserving the cohort term."
            ),
            "adjacent_interpretation_plausible": False,
            "hierarchy_boundary_explicit": True,
            "exact_entity_scope": True,
            "focused_facet": "official cohort members",
            "focused_facet_preserved": True,
            "query_set_collectively_covers_gaps": True,
            "translation_boundary_clear": True,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": True,
            "reason": "The sibling query covers the other evidence gap.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[audited, certified])
        )
        query_set = [focused_query, sibling_query]
        gap_plan = {
            "action": "RESEARCH_AGAIN",
            "gap_type": "two missing facets",
            "follow_up_queries": query_set,
            "reason": "Split the cohort and schedule evidence searches.",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._audit_fact_search_query(
                "List the official cohorts and explain the division schedule.",
                focused_query,
                {
                    "target_entity": "Example organization",
                    "requested_relation": "internal cohorts and divisions",
                    "required_facets": ["cohort list", "division schedule"],
                    "included_scope": "internal organization",
                    "excluded_adjacent_scopes": ["affiliated organizations"],
                },
                query_role="FOCUSED_FOLLOW_UP",
                query_set=query_set,
                gap_plan=gap_plan,
            )

        self.assertEqual(result["approved_search_query"], focused_query)
        audit_payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[0].args[1]
        )
        certification_payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[1].args[1]
        )
        for payload in (audit_payload, certification_payload):
            self.assertEqual(payload["query_role"], "FOCUSED_FOLLOW_UP")
            self.assertEqual(payload["candidate_query_set"], query_set)
            self.assertEqual(payload["evidence_gap_plan"], gap_plan)
            self.assertEqual(
                payload["focused_candidate_before_audit"],
                focused_query,
            )
            self.assertEqual(payload["sibling_queries"], [sibling_query])
            self.assertEqual(
                payload["effective_candidate_query_set"],
                query_set,
            )

        prompts = [
            call.args[0]
            for call in fake_tools.run_ai_prompt.call_args_list
        ]
        self.assertEqual(
            prompts,
            [
                "prompts/fact_query_scope_audit_focused.txt",
                "prompts/fact_query_scope_certify_focused.txt",
            ],
        )
        audit_schema = fake_tools.run_ai_prompt.call_args_list[0].kwargs[
            "json_schema"
        ]
        certification_schema = fake_tools.run_ai_prompt.call_args_list[1].kwargs[
            "json_schema"
        ]
        self.assertIn(
            "approved_focused_facet_preserved",
            audit_schema["required"],
        )
        self.assertIn(
            "query_set_collectively_covers_gaps",
            certification_schema["required"],
        )
        self.assertNotIn(
            "all_facets_preserved",
            certification_schema["properties"],
        )
        prompt = (
            PROJECT_ROOT
            / "prompts"
            / "fact_query_scope_audit_focused.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("source-language", prompt)
        self.assertIn("sibling", prompt)
        certifier_prompt = (
            PROJECT_ROOT
            / "prompts"
            / "fact_query_scope_certify_focused.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("precise positive taxonomy", certifier_prompt)
        self.assertIn("not whether search results", certifier_prompt)
        self.assertNotIn('"accepted":false', certifier_prompt)

    def test_focused_follow_up_cannot_be_replaced_by_sibling_facet(self):
        focused_query = "Example organization official cohort 9 members"
        sibling_query = "Example organization official division schedule"
        wrong_audit = {
            "decision": "REWRITE",
            "proposed_query_scope_match": False,
            "approved_query_scope_match": True,
            "approved_search_query": sibling_query,
            "source_language_boundaries_respected": True,
            "focused_facet": "official cohort members",
            "proposed_focused_facet_preserved": True,
            "approved_focused_facet_preserved": True,
            "query_set_collectively_covers_gaps": True,
            "reason": "Synthetic overconfident first audit.",
        }
        rejected_certification = {
            "accepted": False,
            "literal_scope_paraphrase": "Official division schedule.",
            "strongest_adjacent_interpretation": "An affiliated division.",
            "adjacent_interpretation_plausible": False,
            "hierarchy_boundary_explicit": True,
            "exact_entity_scope": True,
            "focused_facet": "official cohort members",
            "focused_facet_preserved": False,
            "query_set_collectively_covers_gaps": False,
            "translation_boundary_clear": True,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": True,
            "reason": "The rewrite switched to the sibling's facet.",
        }
        repaired_query = (
            "Example organization internal official cohort 9 members"
        )
        repaired_audit = {
            "decision": "REWRITE",
            "proposed_query_scope_match": False,
            "approved_query_scope_match": True,
            "approved_search_query": repaired_query,
            "source_language_boundaries_respected": True,
            "focused_facet": "official cohort members",
            "proposed_focused_facet_preserved": True,
            "approved_focused_facet_preserved": True,
            "query_set_collectively_covers_gaps": True,
            "reason": "The repair preserves this query slot's facet.",
        }
        accepted_certification = {
            "accepted": True,
            "literal_scope_paraphrase": "Internal official cohort 9 members.",
            "strongest_adjacent_interpretation": (
                "A trainee status, defeated by the cohort wording."
            ),
            "adjacent_interpretation_plausible": False,
            "hierarchy_boundary_explicit": True,
            "exact_entity_scope": True,
            "focused_facet": "official cohort members",
            "focused_facet_preserved": True,
            "query_set_collectively_covers_gaps": True,
            "translation_boundary_clear": True,
            "source_language_boundaries_respected": True,
            "standalone_for_search_engine": True,
            "reason": "The repaired candidate and sibling cover both gaps.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[
                wrong_audit,
                rejected_certification,
                repaired_audit,
                accepted_certification,
            ])
        )
        query_set = [focused_query, sibling_query]
        gap_plan = {
            "action": "RESEARCH_AGAIN",
            "gap_type": "cohort and schedule gaps",
            "follow_up_queries": query_set,
            "reason": "Each query owns one gap.",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._audit_fact_search_query(
                "List official cohorts and explain the division schedule.",
                focused_query,
                {
                    "target_entity": "Example organization",
                    "requested_relation": "internal cohorts and divisions",
                    "required_facets": ["cohort list", "division schedule"],
                    "included_scope": "internal organization",
                    "excluded_adjacent_scopes": ["affiliated organizations"],
                },
                query_role="FOCUSED_FOLLOW_UP",
                query_set=query_set,
                gap_plan=gap_plan,
            )

        self.assertEqual(result["approved_search_query"], repaired_query)
        prompts = [
            call.args[0]
            for call in fake_tools.run_ai_prompt.call_args_list
        ]
        self.assertEqual(
            prompts,
            [
                "prompts/fact_query_scope_audit_focused.txt",
                "prompts/fact_query_scope_certify_focused.txt",
                "prompts/fact_query_scope_audit_focused_retry.txt",
                "prompts/fact_query_scope_certify_focused.txt",
            ],
        )
        second_certification_payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[3].args[1]
        )
        self.assertEqual(
            second_certification_payload["effective_candidate_query_set"],
            [repaired_query, sibling_query],
        )
        retry_payload = json.loads(
            fake_tools.run_ai_prompt.call_args_list[2].args[1]
        )
        self.assertEqual(
            retry_payload["independent_certification_failure"],
            {
                **rejected_certification,
                "all_facets_preserved": False,
            },
        )

    def test_missing_evidence_cannot_become_not_yet_available_without_ai_audit(self):
        resolver = {
            "answer_status": "NOT_YET_AVAILABLE",
            "reason": "The supplied pages do not contain a complete list.",
        }
        rejected_audit = {
            "accepted": False,
            "exact_entity_scope": False,
            "exact_temporal_scope": True,
            "status_supported_by_evidence": False,
            "not_missing_evidence_mislabeled_unavailable": False,
            "reason": "Missing and wrong-scope evidence is not non-availability.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[resolver, rejected_audit])
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._resolve_combined_fact(
                "Example internal divisions current",
                [
                    {
                        "title": "Affiliate overview",
                        "description": "Related organizations",
                        "domain": "example.test",
                        "url": "https://example.test/affiliates",
                        "page_success": True,
                        "page_content": "Only affiliated organizations are listed.",
                    }
                ],
                [],
                {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "entity_scope": {
                        "included_scope": "internal divisions",
                        "excluded_adjacent_scopes": ["affiliates"],
                    },
                },
                user_request="What are the current internal divisions?",
            )
        self.assertEqual(result["answer_status"], "INSUFFICIENT")
        self.assertIs(result["accepted"], False)
        self.assertNotIn("answer", result)
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)

    def test_light_persona_preserves_names_and_avoids_duplicate_translation(self):
        prompt = (PROJECT_ROOT / "prompts" / "bekki_persona_light.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Preserve proper names", prompt)
        self.assertIn("Do not append an English duplicate", prompt)

    def test_final_parser_accepts_markdown_fenced_json(self):
        _source, function = function_source(PROJECT_ROOT / "main.py", "parse_ai_result")
        namespace = {"json": json, "print": lambda *args: None}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"),
            namespace,
        )
        value, error = namespace["parse_ai_result"](
            '```json\n{"reply":"有新闻","highlights":[]}\n```'
        )
        self.assertIsNone(error)
        self.assertEqual(value["reply"], "有新闻")

    def test_news_extract_and_curation_use_12b_without_thinking(self):
        extract_source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "_extract_news_events"
        )
        curate_source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "_curate_news_feed"
        )
        for source in (extract_source, curate_source):
            self.assertIn("model_name='gemma4:12b'", source)
            self.assertIn("think=False", source)
            self.assertNotIn("gpt-oss:20b", source)
        self.assertNotIn("32768", extract_source)
        self.assertIn("articles[:6]", extract_source)

    def test_news_extractor_runtime_call_has_bounded_12b_contract(self):
        result = {
            "items": [{
                "index": 1,
                "is_concrete_news": True,
                "content_type": "NEWS",
                "event_title": "Match result",
                "summary": "Manchester United won.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "match-result",
                "uncertainty": "",
                "relevance_score": 90,
                "reason": "Concrete event.",
            }]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=result))
        articles = [{
            "title": "Match result",
            "description": "Manchester United won.",
            "domain": "news.example",
            "url": "https://news.example/match",
            "published": "2026-08-20",
            "source_score": 90,
            "page_success": True,
            "page_content": "Article body",
        }]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            decisions = browser._extract_news_events("Manchester United news", articles)
        self.assertTrue(decisions[1]["is_concrete_news"])
        kwargs = fake_tools.run_ai_prompt.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "gemma4:12b")
        self.assertFalse(kwargs["think"])
        self.assertLessEqual(kwargs["num_ctx"], 12288)

    def test_news_extractor_retries_after_invalid_json_contract(self):
        valid = {
            "items": [{
                "index": 1,
                "is_concrete_news": True,
                "content_type": "NEWS",
                "event_title": "SNH48 election result",
                "summary": "The group announced its election result.",
                "published_at": "2026-08-08",
                "event_date": "2026-08-08",
                "event_key": "snh48-election-2026",
                "uncertainty": "",
                "relevance_score": 90,
                "reason": "Concrete recent event.",
            }]
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[None, valid])
        )
        articles = [{
            "title": "SNH48 election result",
            "description": "The result was announced.",
            "domain": "snh48.com",
            "url": "https://snh48.com/event",
            "published": "2026-08-08",
            "source_score": 95,
            "page_success": True,
            "page_content": "Evidence " * 1000,
        }]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            decisions = browser._extract_news_events("SNH48这几个月的新闻", articles)
        self.assertTrue(decisions[1]["is_concrete_news"])
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)
        retry_call = fake_tools.run_ai_prompt.call_args_list[1]
        self.assertEqual(
            retry_call.args[0],
            "prompts/casper_news_extract_retry.txt",
        )
        self.assertIsInstance(retry_call.kwargs.get("json_schema"), dict)
        self.assertLess(len(retry_call.args[1]), 5000)

    def test_news_final_safe_stop_never_equates_extraction_failure_with_no_news(self):
        _source, function = function_source(
            PROJECT_ROOT / "main.py", "_news_feed_failure_reply"
        )
        namespace = {}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"),
            namespace,
        )
        reply = namespace["_news_feed_failure_reply"]({
            "status": "LIMITED_EVIDENCE"
        })
        self.assertIn("提取没有成功", reply)
        self.assertIn("不能据此说‘没有新闻’", reply)

    def test_fact_lookup_final_safe_stop_blocks_zero_evidence_guess(self):
        _source, function = function_source(
            PROJECT_ROOT / "main.py", "_fact_lookup_failure_reply"
        )
        namespace = {}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"),
            namespace,
        )
        reply = namespace["_fact_lookup_failure_reply"]({
            "status": "LIMITED_EVIDENCE",
            "results": [],
            "answers": [],
        })
        self.assertIn("没有取得足够", reply)
        self.assertIn("不会补写", reply)

    def test_fact_lookup_final_allows_only_ok_accepted_answer(self):
        _source, function = function_source(
            PROJECT_ROOT / "main.py", "_fact_lookup_failure_reply"
        )
        namespace = {}
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"),
            namespace,
        )
        self.assertIsNone(
            namespace["_fact_lookup_failure_reply"]({
                "status": "OK",
                "answers": [{"accepted": True, "answer": "verified"}],
            })
        )

    def test_candidate_fact_validator_requires_every_semantic_check(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value={
                "accepted": True,
                "directly_answers": True,
                "complete_for_request": False,
                "source_supported": True,
                "no_unsupported_additions": True,
                "reason": "Only a partial member list was found.",
            })
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._validate_candidate_answer(
                "SNH48 teams, members, and theater schedule",
                {
                    "title": "Official page",
                    "description": "Partial list",
                    "domain": "snh48.com",
                    "url": "https://snh48.com/partial",
                    "page_content": "Partial evidence",
                },
                "The source lists several members but not the full schedule.",
            )
        self.assertIs(result["accepted"], False)
        schema = fake_tools.run_ai_prompt.call_args.kwargs["json_schema"]
        self.assertIn("complete_for_request", schema["required"])

    def test_candidate_fact_validator_requires_independent_audit(self):
        approved = {
            "accepted": True,
            "directly_answers": True,
            "complete_for_request": True,
            "source_supported": True,
            "no_unsupported_additions": True,
            "reason": "first validator approved",
        }
        rejected = {
            **approved,
            "accepted": False,
            "directly_answers": False,
            "complete_for_request": False,
            "reason": "independent audit found a limitation notice",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=[approved, rejected])
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._validate_candidate_answer(
                "SNH48 teams, members, and theater schedule",
                {
                    "title": "Official page",
                    "description": "Partial list",
                    "domain": "snh48.com",
                    "url": "https://snh48.com/partial",
                    "page_content": "Partial evidence",
                },
                "Several members are listed, but no full schedule is provided.",
            )
        self.assertIs(result["accepted"], False)
        self.assertEqual(fake_tools.run_ai_prompt.call_count, 2)
        self.assertEqual(
            fake_tools.run_ai_prompt.call_args_list[1].args[0],
            "prompts/fact_candidate_validate_audit.txt",
        )

    def test_only_fully_accepted_fact_text_becomes_direct_reply(self):
        answers = [
            {"accepted": False, "answer": "partial"},
            {"accepted": True, "answer": " verified answer "},
        ]
        self.assertEqual(
            browser._accepted_answer_text(answers),
            "verified answer",
        )

    def test_casper_surfaces_news_extraction_failure_as_limited_evidence(self):
        search_result = {
            "status": "LIMITED_EVIDENCE",
            "results": [{"url": "https://snh48.com/news"}],
            "cards": [],
        }
        with patch.object(
            core,
            "validate_plan",
            return_value={"allowed": True, "reason": ""},
        ), patch.object(
            core.adapters,
            "execute_mode",
            return_value=(search_result, None),
        ):
            result = core.execute(
                "SNH48这几个月有什么新闻吗？",
                {"response_mode": "NEWS_FEED"},
                None,
                "",
                lambda _message: None,
            )
        self.assertEqual(result["status"], "limited_evidence")

    def test_news_extractor_keeps_partial_rows_and_recovers_union_label(self):
        result = {
            "items": [{
                "index": 1,
                "is_concrete_news": True,
                "content_type": "NEWS | AGGREGATOR",
                "event_title": "Club announcement",
                "summary": "Manchester United announced an update.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "club-update",
                "uncertainty": "",
                "relevance_score": 88,
                "reason": "Concrete current announcement.",
            }]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=result))
        articles = [
            {
                "title": "Club announcement",
                "description": "Manchester United announced an update.",
                "domain": "manutd.com",
                "url": "https://manutd.com/update",
                "published": "",
                "source_score": 95,
                "page_success": True,
                "page_content": "Article body",
            },
            {
                "title": "Unclassified sixth page",
                "description": "The compact model omitted this row.",
                "domain": "example.com",
                "url": "https://example.com/omitted",
                "published": "",
                "source_score": 50,
                "page_success": True,
                "page_content": "Page body",
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            decisions = browser._extract_news_events("Manchester United news", articles)
        self.assertEqual(set(decisions), {1})
        self.assertEqual(decisions[1]["content_type"], "NEWS")
        self.assertTrue(decisions[1]["is_concrete_news"])

    def test_news_controller_has_nonempty_curation_fallback(self):
        source, _ = function_source(
            PROJECT_ROOT / "casper" / "browser.py", "news_feed_controller"
        )
        self.assertIn("if not selected", source)
        self.assertIn("if item.get('is_concrete_news')", source)
        self.assertIn("Missing per-source AI decision", source)

    def test_news_curation_deduplicates_identical_event_keys(self):
        selected = {
            "selected": [
                {"source_index": 1, "reason": "official preview"},
                {"source_index": 2, "reason": "second publisher"},
                {"source_index": 3, "reason": "different event"},
            ]
        }
        fake_tools = types.SimpleNamespace(run_ai_prompt=Mock(return_value=selected))
        articles = [
            {
                "is_concrete_news": True,
                "event_title": "Team news for Hull opener",
                "event_summary": "Official team news.",
                "event_key": "Man Utd vs Hull City",
                "domain": "manutd.com",
            },
            {
                "is_concrete_news": True,
                "event_title": "Injury boost before Hull",
                "event_summary": "A second report on the same team news.",
                "event_key": "Man Utd vs Hull City",
                "domain": "example.com",
            },
            {
                "is_concrete_news": True,
                "event_title": "Transfer update",
                "event_summary": "A separate transfer event.",
                "event_key": "Man Utd transfer",
                "domain": "example.net",
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._curate_news_feed("latest news", articles)
        self.assertEqual(result, [1, 3])

    def test_news_controller_returns_valid_rows_when_one_source_is_omitted(self):
        candidates = [
            {
                "title": "Club announcement",
                "description": "Manchester United announced an update.",
                "domain": "manutd.com",
                "url": "https://manutd.com/update",
                "published": "",
                "source_score": 95,
            },
            {
                "title": "Unclassified page",
                "description": "This row is omitted by the extractor.",
                "domain": "example.com",
                "url": "https://example.com/omitted",
                "published": "",
                "source_score": 50,
            },
        ]
        decisions = {
            1: {
                "is_concrete_news": True,
                "content_type": "NEWS",
                "event_title": "Club announcement",
                "summary": "Manchester United announced an update.",
                "published_at": "2026-08-20",
                "event_date": "2026-08-20",
                "event_key": "club-update",
                "uncertainty": "",
                "relevance_score": 88,
                "reason": "Concrete current announcement.",
            }
        }
        fake_tools = types.SimpleNamespace(
            score_sources=Mock(return_value=candidates)
        )
        fake_cards = types.SimpleNamespace(clean_cards=lambda values: list(values))
        with patch.dict(
            sys.modules,
            {"tools": fake_tools, "result_cards": fake_cards},
        ), patch.object(
            browser,
            "discover_web",
            return_value={"status": "OK", "results": candidates},
        ), patch.object(
            browser,
            "read_url",
            return_value={"success": True, "content": "Article body"},
        ), patch.object(
            browser,
            "_extract_news_events",
            return_value=decisions,
        ), patch.object(
            browser,
            "_curate_news_feed",
            return_value=[],
        ):
            result = browser.news_feed_controller(
                ["Manchester United latest news"],
                user_request="给我看看最新的曼联新闻",
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["feed"]), 1)
        self.assertEqual(len(result["cards"]), 1)
        self.assertEqual(result["feed"][0]["title"], "Club announcement")

    def test_query_and_consensus_helpers_use_12b_in_both_mirrors(self):
        helper_names = (
            "build_search_query",
            "build_news_queries",
            "build_claim_query",
            "find_consensus",
            "rank_news_results",
        )
        for relative in ("tools.py", "casper/tools.py"):
            for name in helper_names:
                source, _ = function_source(PROJECT_ROOT / relative, name)
                with self.subTest(file=relative, function=name):
                    self.assertIn("model_name='gemma4:12b'", source)
                    self.assertIn("think=False", source)

    def test_generic_shopping_research_no_longer_loads_20b(self):
        for name in (
            "_extract_shopping_products_batch",
            "shopping_research_controller",
        ):
            source, _ = function_source(PROJECT_ROOT / "casper" / "browser.py", name)
            with self.subTest(function=name):
                self.assertNotIn("model_name='gpt-oss:20b'", source)
                self.assertIn("model_name='gemma4:12b'", source)

    def test_adapter_unloads_router_before_nonshopping_research(self):
        source, _ = function_source(
            PROJECT_ROOT / "casper" / "adapters.py", "execute_mode"
        )
        self.assertIn("unload_model('gemma4:12b')", source)
        for mode in ("NEWS_FEED", "FACT_LOOKUP", "CLAIM_CHECK", "SOCIAL_RESEARCH"):
            self.assertIn(repr(mode), source)

    def test_tools_mirrors_remain_identical(self):
        left = ast.dump(
            ast.parse((PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        right = ast.dump(
            ast.parse((PROJECT_ROOT / "casper" / "tools.py").read_text(encoding="utf-8")),
            include_attributes=False,
        )
        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()
