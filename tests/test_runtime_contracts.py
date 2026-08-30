import ast
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import conversation_time
import memory
from casper import memory as casper_memory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RuntimeTopologyTests(unittest.TestCase):
    def test_canonical_imports_resolve_from_project_root(self):
        self.assertEqual(
            Path(importlib.util.find_spec("memory").origin).resolve(),
            PROJECT_ROOT / "memory.py",
        )
        self.assertEqual(
            Path(importlib.util.find_spec("casper").origin).resolve(),
            PROJECT_ROOT / "casper" / "__init__.py",
        )
        self.assertEqual(
            Path(importlib.util.find_spec("casper.core").origin).resolve(),
            PROJECT_ROOT / "casper" / "core.py",
        )

    def test_memory_mirror_has_no_behavior_drift(self):
        root_tree = ast.parse(
            (PROJECT_ROOT / "memory.py").read_text(encoding="utf-8")
        )
        mirror_tree = ast.parse(
            (PROJECT_ROOT / "casper" / "memory.py").read_text(encoding="utf-8")
        )
        self.assertEqual(
            ast.dump(root_tree, include_attributes=False),
            ast.dump(mirror_tree, include_attributes=False),
        )

    def test_router_and_tools_mirrors_have_no_behavior_drift(self):
        for relative in (
            "melchior.py",
            "tools.py",
            "knowledge.py",
            "knowledge_retrieval.py",
        ):
            with self.subTest(relative=relative):
                root_tree = ast.parse(
                    (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                )
                mirror_tree = ast.parse(
                    (PROJECT_ROOT / "casper" / relative).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    ast.dump(root_tree, include_attributes=False),
                    ast.dump(mirror_tree, include_attributes=False),
                )

    def test_verified_knowledge_reaches_magi_without_extra_retrieval_model(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        retrieval = (PROJECT_ROOT / "knowledge_retrieval.py").read_text(
            encoding="utf-8"
        )
        recall_call = (
            "local_knowledge_candidates = knowledge_retrieval.fast_candidates("
        )
        self.assertIn(recall_call, source)
        self.assertIn("knowledge_context=magi_knowledge_context", source)
        self.assertLess(
            source.index(recall_call),
            source.index("magi_route = magi.route_request("),
        )
        self.assertIn("NERV Verified Stable Knowledge Context", source)
        for function_name in (
            "fast_candidates", "format_fast_context", "routing_context"
        ):
            fast_source = ast.unparse(next(
                node
                for node in ast.parse(retrieval).body
                if isinstance(node, ast.FunctionDef)
                and node.name == function_name
            ))
            self.assertNotIn("run_ai_prompt", fast_source)

    def test_daily_knowledge_curator_is_wired_to_idle_runtime(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        core = (PROJECT_ROOT / "nerv" / "core.py").read_text(encoding="utf-8")
        self.assertIn("self.knowledge_curator = KnowledgeCurator", core)
        self.assertIn("def check_daily_knowledge_curator", source)
        self.assertIn("nerv_core.knowledge_curator.run_once()", source)
        self.assertIn(
            "knowledge_curator_timer.timeout.connect(check_daily_knowledge_curator)",
            source,
        )
        for name in (
            "nerv_daily_knowledge_curator.txt",
            "nerv_daily_knowledge_curator_recovery.txt",
            "external_fact_fallback_partition.txt",
            "external_fact_fallback_partition_lifecycle_audit.txt",
            "external_fact_fallback_partition_lifecycle_audit_recovery.txt",
        ):
            self.assertTrue((PROJECT_ROOT / "prompts" / name).is_file())

    def test_verified_curiosity_knowledge_can_seed_idle_continuation(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        curiosity = (
            PROJECT_ROOT / "nerv" / "curiosity.py"
        ).read_text(encoding="utf-8")
        writer = (
            PROJECT_ROOT / "prompts" / "nerv_curiosity_writer.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "nerv_core.curiosity.observe_verified_knowledge(",
            source,
        )
        self.assertIn("def observe_verified_knowledge(", curiosity)
        self.assertIn("DEFAULT_DAILY_LIMIT = 10", curiosity)
        self.assertIn("MAX_DAILY_LIMIT = 10", curiosity)
        self.assertIn("VERIFIED_KNOWLEDGE_IDLE", writer)

    def test_stable_knowledge_review_is_wired_to_idle_runtime(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        core = (PROJECT_ROOT / "nerv" / "core.py").read_text(encoding="utf-8")
        fallback = (
            PROJECT_ROOT / "nerv" / "external_fact_fallback.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self.stable_knowledge_review = StableKnowledgeReviewer", core)
        self.assertIn("def check_daily_stable_knowledge_review", source)
        self.assertIn("nerv_core.stable_knowledge_review.run_once()", source)
        self.assertIn(
            "stable_knowledge_review_timer.timeout.connect(",
            source,
        )
        self.assertNotIn("lifecycle_stability_critic", fallback)
        self.assertFalse(
            (
                PROJECT_ROOT
                / "prompts"
                / "external_fact_fallback_partition_lifecycle_stability_critic.txt"
            ).exists()
        )

    def test_runtime_build_id_is_screenshot_multipass_ocr_v1_10_27(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        manifest = json.loads(
            (PROJECT_ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertIn(
            'BEKKI_BUILD_ID = "bekki-screenshot-multipass-ocr-v1-10-27-20260830"',
            source,
        )
        self.assertIn('print("[BEKKI BUILD]", BEKKI_BUILD_ID', source)
        self.assertEqual(
            manifest["build_id"],
            "bekki-screenshot-multipass-ocr-v1-10-27-20260830",
        )
        self.assertEqual(manifest["package_id"], manifest["build_id"])

    def test_audited_fact_lookup_knowledge_intake_is_async_and_internal(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        core_source = (PROJECT_ROOT / "nerv" / "core.py").read_text(
            encoding="utf-8"
        )
        fallback_source = (
            PROJECT_ROOT / "nerv" / "external_fact_fallback.py"
        ).read_text(encoding="utf-8")
        prompt = (
            PROJECT_ROOT
            / "prompts"
            / "nerv_fact_lookup_knowledge_partition.txt"
        ).read_text(encoding="utf-8")
        self.assertIn('"_fact_knowledge_intake": fact_knowledge_intake', source)
        self.assertIn(
            'result.pop("_fact_knowledge_intake", None)',
            source,
        )
        self.assertIn("fact_knowledge_intake=fact_knowledge_intake", source)
        self.assertIn("intake_audited_fact_lookup(", core_source)
        self.assertLess(
            core_source.index("intake_audited_fact_lookup("),
            core_source.index("curiosity.observe_turn("),
        )
        self.assertIn("strict_source_temporal_scope", fallback_source)
        self.assertIn("source_supported_periods", fallback_source)
        self.assertIn("A completed roster with an exact closed snapshot", prompt)
        self.assertIn("Do not call it changing", prompt)

    def test_recycle_action_disagreement_uses_ai_arbiter(self):
        source = (PROJECT_ROOT / "casper" / "recycle_bin.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        resolver = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_resolve_action"
        )
        resolver_source = ast.unparse(resolver)
        self.assertIn("_plan(message, recent_context)", resolver_source)
        self.assertIn(
            "_classify_restore_intent(message, recent_context)",
            resolver_source,
        )
        self.assertIn("_arbitrate_action(", resolver_source)
        self.assertIn("return arbitrated or 'CLARIFY'", resolver_source)
        self.assertTrue(
            (
                PROJECT_ROOT
                / "prompts"
                / "casper_recycle_action_arbiter.txt"
            ).is_file()
        )

    def test_local_objective_draft_is_audited_before_return(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        audit_index = source.index("objective_fact.should_audit(")
        reroute_index = source.index("[NERV OBJECTIVE FACT REROUTE]")
        return_index = source.index(
            'return {\n        "reply": reply,',
            reroute_index,
        )
        self.assertLess(audit_index, reroute_index)
        self.assertLess(reroute_index, return_index)
        self.assertIn("objective_fact.has_usable_fact_answer", source)
        self.assertIn("objective_fact.unavailable_reply(message)", source)

    def test_user_correction_reverification_is_wired_without_domain_rules(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        objective_source = (
            PROJECT_ROOT / "nerv" / "objective_fact.py"
        ).read_text(encoding="utf-8")
        knowledge_source = (PROJECT_ROOT / "knowledge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("objective_fact.audit_knowledge_correction(", source)
        self.assertIn("knowledge.mark_user_disputed_items(", source)
        self.assertIn(
            "external_fact_fallback.partition_verified_correction_answer(",
            source,
        )
        self.assertIn(
            "knowledge.apply_verified_correction_partitioned_claim(",
            source,
        )
        self.assertIn("knowledge.resolve_user_dispute(", source)
        self.assertIn("[NERV KNOWLEDGE CORRECTION REROUTE]", source)
        self.assertIn("def audit_correction_replacements", objective_source)
        self.assertIn("def mark_user_disputed_items", knowledge_source)
        self.assertIn("revision_history", knowledge_source)
        for name in (
            "nerv_knowledge_correction_audit.txt",
            "nerv_knowledge_correction_partition.txt",
            "nerv_knowledge_correction_resolution.txt",
        ):
            self.assertTrue((PROJECT_ROOT / "prompts" / name).is_file())
        for forbidden in ("SNH48", "李艺彤"):
            self.assertNotIn(forbidden, objective_source)
            self.assertNotIn(forbidden, knowledge_source)


class MainExactResumeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(
            (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        )
        cls.process_request = next(
            node
            for node in cls.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "process_request"
        )

    @staticmethod
    def _calls_pending_clear(nodes):
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "memory"
            and node.func.attr == "clear_pending_action"
            for root in nodes
            for node in ast.walk(root)
        )

    @staticmethod
    def _assigns_exact_active(nodes, value):
        return any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "exact_content_checkpoint_active"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is value
            for root in nodes
            for node in ast.walk(root)
        )

    def test_continue_keeps_checkpoint_until_exact_transition(self):
        continue_branch = next(
            node
            for node in ast.walk(self.process_request)
            if isinstance(node, ast.If)
            and "learning_checkpoint_verdict == 'CONTINUE'"
            in ast.unparse(node.test)
        )
        valid_resume = next(
            node
            for node in continue_branch.body
            if isinstance(node, ast.If)
            and "original_request and content_resume_skill_id"
            in ast.unparse(node.test)
        )

        self.assertTrue(
            self._assigns_exact_active(valid_resume.body, True)
        )
        self.assertFalse(self._calls_pending_clear(valid_resume.body))
        self.assertTrue(self._calls_pending_clear(valid_resume.orelse))

    def test_only_terminal_or_completed_marker_consumes_exact_checkpoint(self):
        transition = next(
            node
            for node in ast.walk(self.process_request)
            if isinstance(node, ast.If)
            and "clear_exact_resume_checkpoint" in ast.unparse(node.test)
            and "exact_resume_completed" in ast.unparse(node.test)
        )
        condition = ast.unparse(transition.test)
        self.assertIn("exact_content_checkpoint_active", condition)
        self.assertIn("casper_result.get('status') != 'human_handoff'", condition)
        self.assertTrue(self._calls_pending_clear(transition.body))
        self.assertTrue(
            self._assigns_exact_active(transition.body, False)
        )

        response_call = next(
            node
            for node in ast.walk(self.process_request)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_ai_response"
        )
        preserve = next(
            keyword
            for keyword in response_call.keywords
            if keyword.arg == "preserve_pending_action"
        )
        self.assertIsInstance(preserve.value, ast.Name)
        self.assertEqual(
            preserve.value.id, "exact_content_checkpoint_active"
        )

    def test_lightweight_runtime_skips_per_turn_ai_context_summary(self):
        update_call = next(
            node
            for node in ast.walk(self.process_request)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "get_ai_response"
        )
        self.assertIsNotNone(update_call)

        get_ai_response = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_ai_response"
        )
        update_calls = [
            node
            for node in ast.walk(get_ai_response)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "context_manager"
            and node.func.attr == "update_context"
        ]
        self.assertEqual(update_calls, [])

        source = ast.unparse(get_ai_response)
        self.assertIn("system_prompt_light", source)
        self.assertIn("context_profile", source)
        self.assertNotIn("16384", source)
        self.assertNotIn("4096,\n        num_predict=4096", source)

    def test_balthasar_runs_only_after_melchior_companion_gate(self):
        calls = [
            node
            for node in ast.walk(self.process_request)
            if isinstance(node, ast.Call)
        ]
        router = next(
            node for node in calls
            if isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "melchior"
            and node.func.attr == "plan_request"
        )
        emotional = next(
            node for node in calls
            if isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "balthasar"
            and node.func.attr == "plan_response"
        )
        self.assertGreater(emotional.lineno, router.lineno)
        self.assertFalse(any(
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "balthasar"
            and node.func.attr == "calibrate_execution"
            for node in calls
        ))
        gate = next(
            node for node in ast.walk(self.process_request)
            if isinstance(node, ast.If)
            and "needs_balthasar" in ast.unparse(node.test)
        )
        self.assertIn(emotional, list(ast.walk(gate)))


class WindowsUpdateInstallerContractTests(unittest.TestCase):
    def test_update_entry_delegates_to_stable_v1_installer(self):
        source = (PROJECT_ROOT / "INSTALL_UPDATE.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("INSTALL_STABLE_V1.ps1", source)
        self.assertIn("-TargetPath $TargetPath", source)

    def test_stable_installer_preserves_user_state_and_rolls_back(self):
        source = (PROJECT_ROOT / "INSTALL_STABLE_V1.ps1").read_text(
            encoding="utf-8"
        )
        for value in (".env", "data", ".git", ".venv", "build", "dist"):
            self.assertIn(value, source)
        self.assertIn("Restore-StableRuntime", source)
        self.assertIn("_bekki_stable_v1_backup_", source)
        self.assertIn("nerv\\external_fact_fallback.py", source)
        self.assertIn("nerv\\knowledge_curator.py", source)
        self.assertNotIn("[IO.Path]::GetRelativePath", source)


class ShoppingRecoveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_is_product_research_route"
        )
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), "main.py", "exec"), namespace)
        cls.is_product_route = staticmethod(namespace["_is_product_research_route"])

    def test_product_route_fails_closed_for_missing_or_empty_results(self):
        self.assertTrue(self.is_product_route("SHOPPING_RESEARCH", {}, None))
        self.assertTrue(
            self.is_product_route("RECOMMENDATION_RESEARCH", {}, None)
        )
        for status in (
            "BROWSER_UNAVAILABLE",
            "HUMAN_HANDOFF",
            "NO_BRAND_POPULARITY_EVIDENCE",
            "NO_VERIFIED_PRODUCTS",
        ):
            with self.subTest(status=status):
                self.assertTrue(
                    self.is_product_route(
                        "RECOMMENDATION_RESEARCH",
                        {},
                        {
                            "status": status,
                            "recommendation_domain": "PRODUCT",
                            "evidence_route": "verified_product_pages",
                            "cards": [],
                        },
                    )
                )
        self.assertFalse(
            self.is_product_route(
                "RECOMMENDATION_RESEARCH",
                {"recommendation_domain": "RESTAURANT"},
                None,
            )
        )

    def test_compact_retry_never_falls_back_to_raw_user_sentence(self):
        source = (PROJECT_ROOT / "tools.py").read_text(encoding="utf-8")
        self.assertIn('model_name="llama3.2:latest"', source)
        self.assertIn('"planning_failed": planning_failed', source)
        self.assertNotIn(
            'queries = [str(user_message).strip()[:220]]',
            source,
        )
        self.assertIn('"prompts/shopping_query_retry.txt"', source)

    def test_generic_shopping_repair_is_not_popularity_gated(self):
        tree = ast.parse((PROJECT_ROOT / "tools.py").read_text(encoding="utf-8"))
        recovery = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_recover_shopping_popularity_plan"
        )
        source = ast.unparse(recovery)
        self.assertNotIn("popularity == 'NONE'", source)
        self.assertIn("'NONE': 'best rated high review count'", source)

    def test_current_shopping_request_does_not_read_resolved_or_profile_state(self):
        tree = ast.parse((PROJECT_ROOT / "tools.py").read_text(encoding="utf-8"))
        planner = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "build_shopping_plan"
        )
        source = ast.unparse(planner)
        self.assertNotIn("resolved_state", source)
        self.assertNotIn("preference_context", source)
        self.assertNotIn("initialize_memory", source)
        self.assertNotIn("load_context", source)
        self.assertIn("_shopping_context_scope", source)

    def test_product_research_prompts_are_part_of_the_runtime(self):
        for name in (
            "shopping_query.txt",
            "shopping_query_retry.txt",
            "shopping_category_verify.txt",
            "shopping_category_translate.txt",
            "casper_product_recommendation_plan.txt",
            "casper_product_recommendation_options.txt",
            "casper_product_recommendation_verify.txt",
            "casper_product_recommendation_recovery.txt",
            "casper_product_recommendation_final.txt",
            "casper_search_summary_answer.txt",
            "casper_search_summary_audit.txt",
            "casper_shopping_brand_evidence.txt",
            "casper_shopping_merchants.txt",
            "casper_shopping_extract.txt",
            "casper_shopping_select.txt",
        ):
            with self.subTest(name=name):
                self.assertTrue((PROJECT_ROOT / "prompts" / name).is_file())

    def test_fact_entity_scope_prompts_are_part_of_the_runtime(self):
        for name in (
            "fact_entity_scope.txt",
            "fact_entity_scope_retry.txt",
            "fact_query_scope_audit.txt",
            "fact_query_scope_audit_retry.txt",
            "fact_query_scope_certify.txt",
            "fact_query_scope_audit_focused.txt",
            "fact_query_scope_audit_focused_retry.txt",
            "fact_query_scope_certify_focused.txt",
            "fact_resolution_audit.txt",
        ):
            with self.subTest(name=name):
                self.assertTrue((PROJECT_ROOT / "prompts" / name).is_file())
                self.assertTrue(
                    (PROJECT_ROOT / "casper" / "prompts" / name).is_file()
                )
        self.assertTrue(
            (
                PROJECT_ROOT
                / "prompts"
                / "external_fact_fallback_policy_audit.txt"
            ).is_file()
        )
        preflight = (
            PROJECT_ROOT / "prompts" / "external_fact_fallback_preflight.txt"
        ).read_text(encoding="utf-8")
        audit = (
            PROJECT_ROOT / "prompts" / "external_fact_fallback_policy_audit.txt"
        ).read_text(encoding="utf-8")
        for prompt in (preflight, audit):
            self.assertIn("MAINTAINED_SET_OR_STRUCTURE", prompt)
            self.assertIn(
                "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT",
                prompt,
            )
            self.assertIn("formal unit", prompt)

    def test_engine_policy_is_fixed_without_a_model_call(self):
        tree = ast.parse(
            (PROJECT_ROOT / "casper" / "browser.py").read_text(encoding="utf-8")
        )
        planner = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_ai_search_engine_policy"
        )
        source = ast.unparse(planner)
        self.assertNotIn("gpt-oss", source)
        self.assertNotIn("run_ai_prompt", source)
        self.assertIn("('google', 'bing')", source)

    def test_shopping_engine_plan_is_task_scoped_and_extraction_is_bounded(self):
        browser_source = (PROJECT_ROOT / "casper" / "browser.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(browser_source)
        controller = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "shopping_research_controller"
        )
        controller_source = ast.unparse(controller)
        self.assertEqual(controller_source.count("_search_engine_policy("), 1)
        self.assertIn("engine_plan=engine_plan", controller_source)
        self.assertNotIn("zip(cards, chosen)", controller_source)
        self.assertLess(
            controller_source.index("unload_model('llama3.2:latest')"),
            controller_source.index("score_sources(user_request, discovered)"),
        )

        for helper_name in (
            "_discover_popular_brands",
            "_discover_shopping_merchants",
        ):
            helper = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == helper_name
            )
            self.assertNotIn("_search_engine_policy(", ast.unparse(helper))

        extractor = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_extract_shopping_products_batch"
        )
        extractor_source = ast.unparse(extractor)
        self.assertIn("num_ctx=8192", extractor_source)
        self.assertIn("num_predict=2200", extractor_source)
        self.assertNotIn("num_ctx=32768", extractor_source)
        self.assertIn("candidates[:12]", extractor_source)
        wrapper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_extract_shopping_products"
        )
        self.assertIn("candidates[:6]", ast.unparse(wrapper))

    def test_multi_merchant_captcha_is_skipped_not_forced_to_handoff(self):
        source = (PROJECT_ROOT / "casper" / "browser.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("[CASPER SHOPPING SKIP PROTECTED]", source)
        self.assertIn('if exclusive_handoff:', source)
        self.assertNotIn(
            'if protected_event == "captcha" or exclusive_handoff:',
            source,
        )

class MemoryPersistenceTests(unittest.TestCase):
    MODULES = (memory, casper_memory)

    def test_pending_ttl_contract(self):
        content_types = {
            "content_learning_continue",
            "content_browser_handoff",
            "skill_user_verification",
        }
        for module in self.MODULES:
            with self.subTest(module=module.__name__):
                for action_type in content_types:
                    self.assertEqual(
                        module._pending_ttl_minutes(action_type),
                        24 * 60,
                    )
                self.assertEqual(
                    module._pending_ttl_minutes("device_action_approval"),
                    15,
                )
                self.assertEqual(module._pending_ttl_minutes(None), 15)

    def test_live_pending_file_uses_type_specific_expiry(self):
        for module in self.MODULES:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temporary:
                pending_path = Path(temporary) / "pending.json"
                with patch.object(module, "DATA_FOLDER", temporary), patch.object(
                    module, "PENDING_FILE", str(pending_path)
                ):
                    module.save_pending_action(
                        {"type": "content_learning_continue"},
                        session_id="session-a",
                    )
                    content_pending = json.loads(
                        pending_path.read_text(encoding="utf-8")
                    )
                    content_delta = (
                        datetime.fromisoformat(content_pending["expires_at"])
                        - datetime.fromisoformat(content_pending["created_at"])
                    ).total_seconds()
                    self.assertEqual(content_delta, 24 * 60 * 60)

                    module.save_pending_action(
                        {"type": "device_action_approval"},
                        session_id="session-a",
                    )
                    approval = json.loads(pending_path.read_text(encoding="utf-8"))
                    approval_delta = (
                        datetime.fromisoformat(approval["expires_at"])
                        - datetime.fromisoformat(approval["created_at"])
                    ).total_seconds()
                    self.assertEqual(approval_delta, 15 * 60)

    def test_atomic_save_keeps_last_known_good_backup(self):
        for module in self.MODULES:
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "state.json"
                module.save_json_file(str(path), {"generation": 1})
                module.save_json_file(str(path), {"generation": 2})

                self.assertEqual(
                    module.load_json_file(str(path)),
                    {"generation": 2},
                )
                self.assertEqual(
                    json.loads((path.parent / "state.json.bak").read_text(encoding="utf-8")),
                    {"generation": 1},
                )

                path.write_text("{broken", encoding="utf-8")
                self.assertEqual(
                    module.load_json_file(str(path), {}),
                    {"generation": 1},
                )
                self.assertFalse(
                    any(item.suffix == ".tmp" for item in path.parent.iterdir())
                )


class ConversationTimeTests(unittest.TestCase):
    def setUp(self):
        self.session = {
            "created_at": "2026-08-17T10:00:00-07:00",
            "messages": [
                {
                    "role": "You",
                    "text": "older request",
                    "created_at": "2026-08-17T10:00:00-07:00",
                },
                {
                    "role": "Bekki",
                    "text": "older response",
                    "created_at": "2026-08-17T10:00:10-07:00",
                },
                {
                    "role": "You",
                    "text": "current saved request",
                    "created_at": "2026-08-17T10:01:00-07:00",
                },
            ],
        }

    def test_default_recent_conversation_includes_latest_message(self):
        rendered = conversation_time.recent_conversation(self.session, limit=2)
        self.assertNotIn("older request", rendered)
        self.assertIn("older response", rendered)
        self.assertIn("current saved request", rendered)

    def test_current_saved_message_can_be_excluded_structurally(self):
        rendered = conversation_time.recent_conversation(
            self.session,
            limit=2,
            exclude_last_message=True,
        )
        self.assertIn("older request", rendered)
        self.assertIn("older response", rendered)
        self.assertNotIn("current saved request", rendered)


class DependencyDocumentationTests(unittest.TestCase):
    def test_required_model_manifest_matches_documented_tags(self):
        manifest = json.loads(
            (PROJECT_ROOT / "MODEL_REQUIREMENTS.json").read_text(encoding="utf-8")
        )
        tags = {item["tag"] for item in manifest["models"]}
        self.assertEqual(
            tags,
            {"gemma4:12b", "gemma4:e4b", "llama3.2:latest"},
        )
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for tag in tags:
            self.assertIn("ollama pull " + tag, readme)


if __name__ == "__main__":
    unittest.main()
