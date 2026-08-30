import unittest
import sys
import types
from unittest.mock import patch

from casper import content_research, content_workflow


class ContentResearchTests(unittest.TestCase):
    def test_content_discovery_uses_bing_only_when_google_is_insufficient(self):
        google_item = {
            "title": "Unrelated browser result",
            "description": "background",
            "domain": "example.test",
            "url": "https://example.test/unrelated",
        }
        bing_item = {
            "title": "FM26 tactic download",
            "description": "tactic and installation guide",
            "domain": "community.test",
            "url": "https://community.test/fm26-tactic",
        }
        engines = []

        def fake_search(_query, count=7, engine="google"):
            engines.append(engine)
            item = google_item if engine == "google" else bing_item
            return {"status": "OK", "results": [item], "engine": engine}

        with patch.object(
            content_research.browser,
            "search_web",
            side_effect=fake_search,
        ), patch.object(
            content_research.browser,
            "_search_engine_policy",
            return_value=("google", "bing"),
        ):
            result = content_research.browser.discover_web(
                "Football Manager 2026 tactics",
                count=6,
                multi_engine=True,
                country_code="US",
                minimum_results=2,
            )
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(engines, ["google", "bing"])
        self.assertEqual(
            result["discovery_type"],
            "casper_browser_multi_engine",
        )

    def test_us_policy_is_fixed_and_does_not_call_ai(self):
        model = unittest.mock.Mock(
            return_value={
                "engines": ["google", "bing"],
                "reason": "US audience coverage",
            }
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy(
                "US", "Football Manager 2026 tactic download"
            )
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_china_code_does_not_enable_regional_engines(self):
        model = unittest.mock.Mock(
            return_value={
                "engines": ["baidu", "sogou"],
                "reason": "Local audience coverage",
            }
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy("CN")
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_korea_code_does_not_enable_naver(self):
        model = unittest.mock.Mock(
            return_value={
                "engines": ["naver", "google"],
                "reason": "Naver is locally popular",
            }
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy("KR")
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_chinese_query_does_not_change_us_engine_pair(self):
        model = unittest.mock.Mock(
            side_effect=[
                {
                    "engines": ["google", "bing_cn"],
                    "reason": "incorrectly inferred China from query language",
                },
                {
                    "engines": ["google", "duckduckgo"],
                    "reason": "global coverage for the detected US audience",
                },
            ]
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy(
                "US", "如何打开游戏内容文件夹"
            )
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_unknown_region_still_uses_us_oriented_pair(self):
        model = unittest.mock.Mock(
            side_effect=[
                {
                    "engines": ["naver", "google"],
                    "reason": "unsupported regional guess",
                },
                {
                    "engines": ["duckduckgo", "bing"],
                    "reason": "global coverage without a grounded region",
                },
            ]
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}), patch(
            "location.detect_location",
            return_value={
                "country_code": "",
                "country_name": "",
                "location_name": "Unknown",
                "time_zone": "",
                "source": "unknown",
                "confidence": "unknown",
            },
        ):
            engines = content_research.browser._search_engine_policy(
                None, "game content folder documentation"
            )
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_location_metadata_does_not_trigger_engine_ai(self):
        model = unittest.mock.Mock(
            return_value={
                "engines": ["google", "duckduckgo"],
                "reason": "global engines for conflicting regional signals",
            }
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}), patch(
            "location.detect_location",
            return_value={
                "country_code": "CN",
                "country_name": "China",
                "location_name": "China",
                "time_zone": "Pacific Standard Time",
                "source": "windows_home_location",
                "confidence": "medium",
            },
        ):
            engines = content_research.browser._search_engine_policy(
                None, "game content folder documentation"
            )
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_invalid_ai_outputs_are_irrelevant_to_fixed_policy(self):
        valid = {
            "engines": ["google", "duckduckgo"],
            "reason": "Independent coverage",
        }
        for primary in (None, {"engines": ["unknown"]}):
            with self.subTest(primary=primary):
                model = unittest.mock.Mock(side_effect=[primary, valid])
                tools_stub = types.SimpleNamespace(run_ai_prompt=model)
                content_research.browser._ai_search_engine_policy.cache_clear()
                with patch.dict(sys.modules, {"tools": tools_stub}):
                    engines = content_research.browser._search_engine_policy(
                        "US", "managed-browser research"
                    )

                self.assertEqual(engines, ("google", "bing"))
                model.assert_not_called()

    def test_invalid_ai_engine_plan_never_runs(self):
        model = unittest.mock.Mock(
            side_effect=[
                {"engines": ["unknown"], "reason": "invalid"},
                {"engines": ["google", "google"], "reason": "invalid"},
            ]
        )
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy("GB")
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_engine_planner_http_failure_cannot_affect_fixed_policy(self):
        model = unittest.mock.Mock(side_effect=RuntimeError("ollama 500"))
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        content_research.browser._ai_search_engine_policy.cache_clear()
        with patch.dict(sys.modules, {"tools": tools_stub}):
            engines = content_research.browser._search_engine_policy(
                "US", "popular cups"
            )
        self.assertEqual(engines, ("google", "bing"))
        model.assert_not_called()

    def test_content_workflow_requests_dual_channel_discovery(self):
        plan = {"queries": ["Football Manager 2026 tactics"]}
        with patch.object(
            content_research.browser,
            "discover_web",
            return_value={"status": "NO_RESULTS", "results": []},
        ) as discover:
            content_research._discover(plan)
        self.assertTrue(discover.call_args.kwargs["multi_engine"])

    def test_active_engine_catalog_contains_only_google_and_bing(self):
        self.assertEqual(
            [item["id"] for item in content_research.browser.SEARCH_ENGINE_CATALOG],
            ["google", "bing"],
        )

    def test_content_ai_uses_gpt_oss_json_contract(self):
        model = unittest.mock.Mock(return_value={"queries": ["FM26 tactics"]})
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": tools_stub}):
            result = content_research._ai(
                "prompts/casper_content_query_review.txt",
                {"proposed_queries": ["FM26 tactics"]},
                700,
            )
        self.assertEqual(result["queries"], ["FM26 tactics"])
        self.assertTrue(model.call_args.kwargs["expect_json"])
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")
        self.assertEqual(model.call_args.kwargs["num_predict"], 700)

    def test_research_plan_retries_empty_model_output_compactly(self):
        valid = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "requested_outcome": "find and prepare installation",
            "version_constraints": ["FM26"],
            "selection_criteria": ["compatibility"],
            "queries": ["best FM26 Manchester United tactic install guide"],
        }
        with patch.object(
            content_research, "_ai", side_effect=[None, valid]
        ) as model:
            plan = content_research._plan("找 FM26 战术", "long context")
        self.assertEqual(plan["target_app"], "Football Manager 2026")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_research_plan.txt",
        )
        self.assertEqual(model.call_args_list[0].args[2], 700)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_research_plan_retry.txt",
        )
        self.assertEqual(model.call_args_list[1].args[2], 900)
        retry_payload = model.call_args_list[1].args[1]
        self.assertNotIn("recent_context", retry_payload)

    def test_candidate_plan_receives_learned_procedure(self):
        valid = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "requested_outcome": "find a strong downloadable tactic",
            "version_constraints": ["FM26"],
            "selection_criteria": ["tested performance"],
            "queries": ["Football Manager 2026 tested tactic download"],
        }
        procedure = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "expected_file_types": [".fmf"],
        }
        with patch.object(
            content_research, "_ai", return_value=valid
        ) as model:
            content_research._plan(
                "找适合曼联的战术", "", procedure=procedure
            )
        payload = model.call_args.args[1]
        self.assertEqual(
            payload["learned_installation_procedure"]["expected_file_types"],
            [".fmf"],
        )

    def test_research_plan_removes_structural_values_from_fit_context(self):
        valid = {
            "target_app": "FM2026",
            "content_kind": "tactics",
            "requested_outcome": "find strong tactics",
            "fit_context": ["Manchester United", "FM2026", "tactics"],
            "version_constraints": ["FM2026"],
            "selection_criteria": ["strength"],
            "queries": ["FM2026 tactics"],
        }
        with patch.object(content_research, "_ai", return_value=valid):
            plan = content_research._plan("找适合曼联的战术", "")
        self.assertEqual(plan["fit_context"], ["Manchester United"])
        self.assertFalse(plan["fit_context_is_content_identity"])

    def test_query_compliance_does_not_receive_original_request(self):
        plan = {
            "target_app": "FM2026",
            "content_kind": "tactics",
            "fit_context": ["Manchester United"],
            "fit_context_is_content_identity": False,
        }
        with patch.object(
            content_research, "_ai", return_value={"compliant": True}
        ) as model:
            accepted = content_research._queries_are_compliant(
                "找适合曼联的战术", plan, ["FM2026 tactics download"]
            )
        self.assertTrue(accepted)
        payload = model.call_args.args[1]
        self.assertNotIn("request", payload)
        self.assertEqual(payload["fit_context"], ["Manchester United"])
        self.assertFalse(payload["fit_context_is_content_identity"])

    def test_query_compliance_adjudicates_false_negative_with_gpt_oss(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "version_constraints": ["FM26"],
            "fit_context": ["Manchester United squad"],
            "fit_context_is_content_identity": False,
        }
        with patch.object(
            content_research,
            "_ai",
            side_effect=[
                {"compliant": False},
                {"compliant": True, "reason": "No fit-context term appears"},
            ],
        ) as model:
            accepted = content_research._queries_are_compliant(
                "找适合曼联的战术",
                plan,
                ["Football Manager 2026 best tested tactics download"],
            )
        self.assertTrue(accepted)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_query_compliance_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"],
            "gemma4:12b",
        )
        payload = model.call_args_list[1].args[1]
        self.assertNotIn("request", payload)
        self.assertEqual(payload["version_constraints"], ["FM26"])

    def test_query_review_can_replace_ambiguous_acronym_searches(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "fit_context": ["Manchester United squad"],
            "version_constraints": ["FM26"],
            "selection_criteria": ["tested"],
            "queries": ["FM2026 战术"],
        }
        reviewed = {
            "queries": [
                '"Football Manager 2026" best tested tactic download install guide'
            ]
        }
        with patch.object(
            content_research,
            "_ai",
            side_effect=[reviewed, {"compliant": True}],
        ) as model:
            result = content_research._review_queries("找曼联战术", plan)
        self.assertEqual(model.call_args_list[0].args[2], 500)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertIn("Football Manager 2026", result["queries"][0])
        self.assertNotIn("Manchester United", result["queries"][0])
        self.assertNotEqual(result["queries"], plan["queries"])

    def test_query_review_fails_closed_when_reviewer_output_is_invalid(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "fit_context": ["Manchester United"],
            "version_constraints": ["FM26"],
            "selection_criteria": ["suitable for the current squad"],
            "queries": ["FM26 Manchester United best tactic"],
        }
        with patch.object(content_research, "_ai", return_value=None):
            result = content_research._review_queries("找一套适合曼联的战术", plan)
        self.assertIsNone(result)

    def test_query_review_retries_when_ai_detects_fit_context_leakage(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "fit_context": ["Manchester United"],
            "version_constraints": ["FM26"],
            "selection_criteria": ["strong and compatible"],
            "queries": ["FM26 曼联最强战术"],
        }
        with patch.object(
            content_research,
            "_ai",
            side_effect=[
                {"queries": ["FM26 曼联最强战术"]},
                {"compliant": False},
                {"compliant": False},
                {"queries": ["Football Manager 2026 best tested tactic"]},
                {"compliant": True},
            ],
        ):
            result = content_research._review_queries("找适合曼联的战术", plan)
        self.assertEqual(
            result["queries"],
            ["Football Manager 2026 best tested tactic"],
        )

    def test_query_review_uses_sanitized_third_attempt(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "fit_context": ["Manchester United"],
            "version_constraints": ["FM26"],
            "selection_criteria": ["suitable for current squad"],
            "queries": ["FM26 Manchester United tactic"],
        }
        with patch.object(
            content_research,
            "_ai",
            side_effect=[
                None,
                {"queries": ["FM26 Manchester United tactic"]},
                {"compliant": False},
                {"compliant": False},
                {"queries": ["Football Manager 2026 tested tactic download"]},
                {"compliant": True},
            ],
        ) as model:
            result = content_research._review_queries("找适合曼联的战术", plan)
        third_payload = model.call_args_list[4].args[1]
        self.assertNotIn("request", third_payload)
        self.assertNotIn("fit_context", third_payload)
        self.assertEqual(
            result["queries"],
            ["Football Manager 2026 tested tactic download"],
        )

    def test_source_rank_rejects_unreturned_and_invented_ids(self):
        discovered = [
            {
                "id": "relevant-id",
                "title": "Football Manager tactic",
                "description": "guide",
                "domain": "example.test",
                "url": "https://example.test/guide",
            },
            {
                "id": "microsoft-id",
                "title": "Microsoft",
                "description": "software",
                "domain": "microsoft.com",
                "url": "https://microsoft.com",
            },
        ]
        with patch.object(
            content_research,
            "_ai",
            return_value={
                "ordered_source_ids": ["relevant-id", "invented-id"]
            },
        ):
            ranked = content_research._rank_discovered(
                "find tactic", {"target_app": "Football Manager"}, discovered
            )
        self.assertEqual([item["id"] for item in ranked], ["relevant-id"])

    def test_source_rank_retries_empty_output_without_fit_context(self):
        discovered = [{
            "id": "guide-id",
            "title": "FM26 tactic installation guide",
            "description": "Download and import tactics",
            "domain": "community.test",
            "url": "https://community.test/guide",
        }]
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "requested_outcome": "find and install",
            "version_constraints": ["FM26"],
            "fit_context": ["Manchester United squad"],
            "queries": ["Football Manager 2026 tactic download"],
        }
        with patch.object(
            content_research,
            "_ai",
            side_effect=[None, {"ordered_source_ids": ["guide-id"]}],
        ) as model:
            ranked = content_research._rank_discovered(
                "找适合曼联的战术", plan, discovered
            )
        self.assertEqual([item["id"] for item in ranked], ["guide-id"])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].args[2], 2000)
        self.assertEqual(model.call_args_list[1].args[2], 1800)
        payload = model.call_args_list[0].args[1]
        self.assertNotIn("request", payload)
        self.assertNotIn("fit_context", payload["research_plan"])

    def test_retry_query_packet_cannot_reintroduce_fit_context(self):
        plan = {
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "requested_outcome": "find and install",
            "version_constraints": ["FM26"],
            "fit_context": ["Manchester United squad"],
        }
        discovered = [{
            "title": "Unrelated result",
            "description": "noise",
            "domain": "example.test",
        }]
        with patch.object(
            content_research,
            "_ai",
            return_value={"queries": ["Football Manager 2026 tactic guide"]},
        ) as model, patch.object(
            content_research,
            "_queries_are_compliant",
            return_value=True,
        ):
            queries = content_research._retry_queries(
                "找适合曼联的战术", plan, discovered
            )
        self.assertEqual(queries, ["Football Manager 2026 tactic guide"])
        payload = model.call_args.args[1]
        self.assertNotIn("request", payload)
        self.assertNotIn("fit_context", payload["research_plan"])

    def test_manifest_url_is_copied_from_browser_not_model(self):
        plan = {"target_app": "Example Game", "content_kind": "mod"}
        pages = [{
            "id": "source-id",
            "title": "Trusted Mod Guide",
            "domain": "example.test",
            "url": "https://example.test/real-page",
            "content": "Install the Community Mod in the game's Mods folder.",
        }]
        model_output = {
            "manifests": [{
                "source_id": "source-id",
                "artifact_name": "Community Mod",
                "target_app": "Example Game",
                "content_kind": "mod",
                "compatibility": "Current version",
                "evidence_summary": "The page provides an install guide.",
                "expected_file_types": [".zip"],
                "destination_hints": ["the game's Mods folder"],
                "installation_steps": ["Extract into Mods"],
                "post_install_steps": ["Enable in game"],
                "source_url": "https://invented.invalid/payload.zip",
            }]
        }
        with patch.object(content_research, "_ai", return_value=model_output):
            manifests = content_research._extract_manifests(
                "find and install a mod", plan, pages
            )
        self.assertEqual(
            manifests[0]["source_url"], "https://example.test/real-page"
        )
        self.assertNotIn("invented.invalid", str(manifests[0]))

    def test_extract_rejects_invented_source_id(self):
        pages = [{
            "id": "real-id",
            "title": "Guide",
            "domain": "example.test",
            "url": "https://example.test/guide",
            "content": "Guide content",
        }]
        output = {
            "manifests": [{
                "source_id": "invented-id",
                "artifact_name": "Fake Mod",
            }]
        }
        with patch.object(content_research, "_ai", return_value=output):
            manifests = content_research._extract_manifests(
                "install", {"target_app": "Game", "content_kind": "mod"}, pages
            )
        self.assertEqual(manifests, [])

    def test_manifest_extraction_combines_bounded_pages_in_one_ai_call(self):
        pages = [
            {
                "id": "one",
                "title": "One",
                "domain": "one.test",
                "url": "https://one.test/guide",
                "content": "first",
            },
            {
                "id": "two",
                "title": "Two",
                "domain": "two.test",
                "url": "https://two.test/guide",
                "content": "second",
            },
        ]
        with patch.object(
            content_research,
            "_ai",
            return_value={"manifests": []},
        ) as model:
            content_research._extract_manifests(
                "install mod", {"target_app": "Game", "content_kind": "mod"}, pages
            )
        self.assertEqual(model.call_count, 1)
        self.assertEqual(len(model.call_args.args[1]["pages"]), 2)
        self.assertEqual(model.call_args.args[2], 3000)
        self.assertEqual(model.call_args.kwargs["num_ctx"], 16384)

    def test_manifest_supporting_ids_are_copied_only_from_browser_pages(self):
        pages = [
            {
                "id": "artifact-id",
                "title": "Named FM26 tactic",
                "domain": "artifact.test",
                "url": "https://artifact.test/tactic",
                "content": "A named downloadable tactic.",
            },
            {
                "id": "guide-id",
                "title": "FM26 installation guide",
                "domain": "guide.test",
                "url": "https://guide.test/install",
                "content": "Place the .fmf file in the tactics folder.",
            },
        ]
        output = {"manifests": [{
            "source_id": "artifact-id",
            "supporting_source_ids": ["guide-id", "invented-id"],
            "artifact_name": "Named FM26 tactic",
            "destination_hints": ["FM26 tactics folder"],
            "installation_steps": ["Move the .fmf file into the folder"],
        }]}
        with patch.object(content_research, "_ai", return_value=output):
            manifests = content_research._extract_manifests(
                "install tactic",
                {"target_app": "FM26", "content_kind": "tactic"},
                pages,
            )
        self.assertEqual(manifests[0]["supporting_source_ids"], ["guide-id"])

    def test_manifest_extraction_can_use_learned_installation_knowledge(self):
        pages = [{
            "id": "artifact-id",
            "title": "Winning FM26 tactic",
            "domain": "artifact.test",
            "url": "https://artifact.test/tactic",
            "content": "A concrete downloadable FM26 tactic.",
        }]
        procedure = {
            "expected_file_types": [".fmf"],
            "destination_hints": ["FM26 tactics folder"],
            "installation_steps": ["Move the file into tactics"],
        }
        output = {"manifests": [{
            "source_id": "artifact-id",
            "artifact_name": "Winning FM26 tactic",
            "destination_hints": ["FM26 tactics folder"],
            "installation_steps": ["Move the file into tactics"],
        }]}
        with patch.object(
            content_research, "_ai", return_value=output
        ) as model:
            manifests = content_research._extract_manifests(
                "find tactic",
                {"target_app": "FM26", "content_kind": "tactic"},
                pages,
                procedure=procedure,
            )
        self.assertEqual(len(manifests), 1)
        self.assertEqual(
            model.call_args.args[1]["learned_installation_procedure"]
            ["expected_file_types"],
            [".fmf"],
        )

    def test_manifest_extraction_retries_invalid_json_contract(self):
        pages = [{
            "id": "source-id",
            "title": "Tactic",
            "domain": "example.test",
            "url": "https://example.test/tactic",
            "content": "Tactic and guide",
        }]
        with patch.object(
            content_research,
            "_ai",
            side_effect=[None, {"manifests": []}],
        ) as model:
            manifests = content_research._extract_manifests(
                "install tactic",
                {"target_app": "FM26", "content_kind": "tactic"},
                pages,
            )
        self.assertEqual(manifests, [])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[1].args[2], 2600)
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 16384)

    def test_generic_workflow_routes_online_request_to_research(self):
        expected = {"action": "learned_content_skill_candidate"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.content_learning.execute", return_value=expected
        ) as execute:
            result = content_workflow.execute(
                "网上找一个游戏 mod 并安装", "context"
            )
        execute.assert_called_once_with(
            "网上找一个游戏 mod 并安装",
            "",
            status_callback=None,
            requested_skill_scope="INSTALL_CONTENT",
        )
        self.assertEqual(result, expected)

    def test_local_fm_adapter_is_only_one_registered_branch(self):
        expected = {"action": "installed_fm_tactic"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_stage",
            return_value="INSTALL_LOCAL_CONTENT",
        ), patch(
            "casper.game_content.execute", return_value=expected
        ) as execute:
            result = content_workflow.execute("安装已下载战术", "")
        execute.assert_called_once_with("安装已下载战术", "")
        self.assertEqual(result, expected)

    def test_authorized_workflow_uses_two_choice_stage_ai(self):
        expected = {"action": "learned_content_skill_candidate"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ) as authorized, patch.object(
            content_workflow, "_classify_stage"
        ) as broad, patch(
            "casper.content_learning.execute", return_value=expected
        ):
            result = content_workflow.execute(
                "找战术并整理安装方案", "", content_authorized=True
            )
        authorized.assert_called_once()
        broad.assert_not_called()
        self.assertEqual(result, expected)

    def test_confirmed_learning_checkpoint_resumes_exact_skill_candidate(self):
        procedure = {
            "id": "candidate-id",
            "target_app": "FM26",
            "skill_scope": "INSTALL_CONTENT",
        }
        expected = {"action": "installed_fm_tactic"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch(
            "casper.skill_registry.load_pending",
            return_value=procedure,
        ), patch(
            "casper.skill_registry.load_verified",
            return_value=None,
        ), patch(
            "casper.content_research.execute", return_value=expected
        ) as execute, patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ) as classifier:
            result = content_workflow.execute(
                "找战术并安装",
                "context",
                content_authorized=True,
                resume_skill_id="candidate-id",
            )
        classifier.assert_called_once_with("找战术并安装", "")
        execute.assert_called_once_with(
            "找战术并安装",
            "",
            status_callback=None,
            procedure=procedure,
        )
        self.assertEqual(result, expected)

    def test_resumed_candidate_failure_remains_retryable(self):
        procedure = {
            "id": "candidate-id",
            "status": "pending_execution",
            "target_app": "FM26",
            "skill_scope": "INSTALL_CONTENT",
            "destination_name": "FM26 tactics",
            "original_request": "找战术并安装",
        }
        failed = {
            "success": False,
            "needs_clarification": True,
            "clarification": "没有找到下载链接。",
        }
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.load_pending", return_value=procedure
        ), patch(
            "casper.skill_registry.load_verified", return_value=None
        ), patch(
            "casper.content_research.execute", return_value=failed
        ):
            result = content_workflow.execute(
                "找战术并安装", "", resume_skill_id="candidate-id"
            )
        self.assertTrue(result["content_installation_retry_available"])
        self.assertEqual(result["resume_skill_id"], "candidate-id")
        self.assertEqual(result["original_request"], "找战术并安装")

    def test_candidate_selection_downloads_with_exact_learned_procedure(self):
        plan = {
            "target_app": "FM26",
            "content_kind": "tactic",
            "queries": ["FM26 tactic download"],
        }
        source = {
            "id": "source-id",
            "title": "Tactic",
            "description": "download",
            "domain": "example.test",
            "url": "https://example.test/tactic",
        }
        page = {**source, "content": "downloadable tactic"}
        manifest = {
            "id": "manifest-id",
            "artifact_name": "Tactic",
            "source_url": source["url"],
        }
        procedure = {
            "id": "candidate-id",
            "status": "pending_execution",
            "local_adapter": "FM_TACTIC",
        }
        installed = {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
            "name": "winner.fmf",
        }
        marked = {
            **procedure,
            "status": "pending_user_verification",
            "target_app": "FM26",
        }
        with patch.object(
            content_research, "_plan", return_value=plan
        ), patch.object(
            content_research, "_review_queries", return_value=plan
        ), patch.object(
            content_research, "_discover", return_value=([source], None)
        ), patch.object(
            content_research, "_rank_discovered", return_value=[source]
        ), patch.object(
            content_research, "_read_candidates", return_value=[page]
        ), patch.object(
            content_research, "_extract_manifests", return_value=[manifest]
        ), patch.object(
            content_research, "_choose_manifest", return_value=manifest
        ), patch(
            "casper.content_download.execute", return_value=installed
        ) as download, patch(
            "casper.skill_registry.mark_execution_success",
            return_value=marked,
        ) as mark:
            result = content_research.execute(
                "find and install", "", procedure=procedure
            )
        download.assert_called_once_with(manifest, procedure)
        mark.assert_called_once_with("candidate-id", installed, manifest)
        self.assertEqual(
            result["action"],
            "content_installation_awaiting_user_verification",
        )
        self.assertTrue(result["requires_user_verification"])

    def test_verified_semantic_skill_skips_learning_phase(self):
        skill = {
            "id": "skill-id",
            "status": "verified",
            "target_app": "FM26",
            "skill_scope": "INSTALL_CONTENT",
        }
        expected = {"action": "installed_fm_tactic"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.match_pending_resume", return_value=None
        ), patch(
            "casper.skill_registry.match_verified", return_value=skill
        ) as match, patch(
            "casper.content_research.execute", return_value=expected
        ) as research, patch(
            "casper.content_learning.execute"
        ) as learning:
            result = content_workflow.execute(
                "给我装一套适合红魔的阵型",
                "",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        match.assert_called_once()
        research.assert_called_once_with(
            "给我装一套适合红魔的阵型",
            "",
            status_callback=None,
            procedure=skill,
        )
        learning.assert_not_called()
        self.assertEqual(result, expected)

    def test_lost_checkpoint_never_broadly_restores_pending_candidate(self):
        expected = {"action": "learned_again"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="NEEDS_CONTEXT",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.match_pending_resume",
            return_value={"decision": "CLARIFY"},
        ) as match, patch(
            "casper.skill_registry.match_verified", return_value=None
        ), patch(
            "casper.content_learning.execute", return_value=expected
        ) as learning:
            result = content_workflow.execute(
                "继续",
                "Bekki: 如果要继续搜索和安装，请回复继续。",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        match.assert_not_called()
        learning.assert_called_once_with(
            "继续",
            "Bekki: 如果要继续搜索和安装，请回复继续。",
            status_callback=None,
            requested_skill_scope="INSTALL_CONTENT",
        )
        self.assertEqual(result, expected)

    def test_different_pending_operations_are_invisible_to_normal_lookup(self):
        expected = {"action": "fresh_learning"}
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="NEEDS_CONTEXT",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.match_pending_resume",
            return_value={"decision": "CLARIFY"},
        ) as pending, patch(
            "casper.skill_registry.match_verified", return_value=None
        ), patch(
            "casper.content_learning.execute", return_value=expected
        ) as learning:
            result = content_workflow.execute(
                "继续",
                "Bekki: 如果需要，请回复继续。",
                content_authorized=True,
                skill_lookup_requested=True,
            )
        pending.assert_not_called()
        learning.assert_called_once()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
