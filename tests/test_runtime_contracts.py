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
        for relative in ("melchior.py", "tools.py"):
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

    def test_runtime_build_id_is_ui_personalization_v1(self):
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            'BEKKI_BUILD_ID = "bekki-ui-personalization-v1-20260826"',
            source,
        )
        self.assertIn('print("[BEKKI BUILD]", BEKKI_BUILD_ID', source)


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
            {"gemma3:12b", "gemma3:4b", "llama3.2:latest"},
        )
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for tag in tags:
            self.assertIn("ollama pull " + tag, readme)


if __name__ == "__main__":
    unittest.main()
