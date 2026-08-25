import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def _load_melchior():
    stubs = {
        "context": types.SimpleNamespace(load_context=lambda: {}),
        "document": types.SimpleNamespace(has_document=lambda: False),
        "memory": types.SimpleNamespace(
            initialize_memory=lambda: {},
            get_long_term_context=lambda _data: "",
        ),
        "magi": types.SimpleNamespace(
            audit_route=lambda *_a, previous_route=None, **_k: previous_route,
        ),
        "location": types.SimpleNamespace(
            get_localization_context=lambda: "{}",
        ),
        "tools": types.SimpleNamespace(
            run_ai_prompt=lambda *_a, **_k: None,
            unload_model=lambda *_a, **_k: None,
        ),
        "vision": types.SimpleNamespace(has_image=lambda: False),
    }
    path = Path(__file__).resolve().parents[1] / "melchior.py"
    spec = importlib.util.spec_from_file_location("melchior_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class MelchiorRecoveryTests(unittest.TestCase):
    def test_device_file_scope_is_preserved_only_for_device_actions(self):
        module = _load_melchior()
        device_plan = module._normalize_plan({
            "response_mode": "DEVICE_ACTION",
            "device_scope": "FILE_ACTION",
        })
        local_plan = module._normalize_plan({
            "response_mode": "LOCAL_ANSWER",
            "device_scope": "FILE_ACTION",
        })
        self.assertEqual(device_plan["device_scope"], "FILE_ACTION")
        self.assertIsNone(local_plan["device_scope"])

    def test_ordinary_recommendation_defaults_to_minimal_task_mode(self):
        module = _load_melchior()
        plan = module._normalize_plan({
            "response_mode": "RECOMMENDATION_RESEARCH",
            "recommendation_domain": "PRODUCT",
        })
        self.assertEqual(plan["interaction_mode"], "TASK")
        self.assertEqual(plan["context_profile"], "MINIMAL")
        self.assertFalse(plan["needs_balthasar"])

    def test_local_emotional_support_enables_companion_context(self):
        module = _load_melchior()
        plan = module._normalize_plan({
            "response_mode": "LOCAL_ANSWER",
            "interaction_mode": "COMPANION",
            "context_profile": "MINIMAL",
        })
        self.assertEqual(plan["context_profile"], "COMPANION")
        self.assertTrue(plan["needs_balthasar"])

    def test_companion_response_mode_schema_alias_is_repaired_without_retry(self):
        module = _load_melchior()
        raw = {
            "response_mode": "COMPANION",
            "interaction_mode": "COMPANION",
            "context_profile": "CONVERSATION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "reason": "emotional support",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw) as model:
            plan = module.plan_request("今天工作好累，陪我聊一会儿吧")
        self.assertEqual(plan["response_mode"], "LOCAL_ANSWER")
        self.assertEqual(plan["interaction_mode"], "COMPANION")
        self.assertEqual(plan["context_profile"], "COMPANION")
        self.assertTrue(plan["needs_balthasar"])
        self.assertEqual(model.call_count, 1)

    def test_nonlocal_route_cannot_enable_balthasar(self):
        module = _load_melchior()
        plan = module._normalize_plan({
            "response_mode": "FACT_LOOKUP",
            "interaction_mode": "COMPANION",
            "context_profile": "COMPANION",
        })
        self.assertEqual(plan["interaction_mode"], "TASK")
        self.assertEqual(plan["context_profile"], "MINIMAL")
        self.assertFalse(plan["needs_balthasar"])

    def test_simple_app_launch_forces_one_off_scope_even_if_ai_requests_lookup(self):
        module = _load_melchior()
        raw = {
            "response_mode": "DEVICE_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "lookup",
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "open Steam",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw) as model:
            plan = module.plan_request("打开 Steam")
        self.assertEqual(plan["skill_route"], "none")
        self.assertFalse(plan.get("content_workflow_selected", False))
        self.assertEqual(model.call_count, 1)

    def test_simple_app_launch_overrides_ai_local_answer_and_companion(self):
        module = _load_melchior()
        raw = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "interaction_mode": "COMPANION",
            "context_profile": "COMPANION",
            "reason": "casual game conversation",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw):
            plan = module.plan_request("打开原神")
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertEqual(plan["interaction_mode"], "TASK")
        self.assertEqual(plan["context_profile"], "MINIMAL")
        self.assertFalse(plan["needs_balthasar"])
        self.assertEqual(plan["skill_route"], "none")

    def test_content_folder_launch_is_not_reduced_to_simple_app_scope(self):
        module = _load_melchior()
        self.assertFalse(module._is_direct_application_launch("打开 FM26 战术文件夹"))
        self.assertTrue(module._is_direct_application_launch("打开 Steam"))

    def test_explicit_steam_game_launch_has_its_own_bounded_scope(self):
        module = _load_melchior()
        raw = {
            "response_mode": "DEVICE_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "lookup",
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "reason": "launch an installed Steam game",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw) as model:
            plan = module.plan_request("打开 Steam 里的 FM26")
        self.assertTrue(plan["steam_game_launch_selected"])
        self.assertEqual(plan["skill_route"], "none")
        self.assertFalse(plan.get("content_workflow_selected", False))
        self.assertEqual(model.call_count, 1)

    def test_steam_library_list_forces_read_only_local_device_scope(self):
        module = _load_melchior()
        raw = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "lookup",
            "interaction_mode": "COMPANION",
            "context_profile": "CONVERSATION",
            "reason": "talk about a Steam library",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw) as model:
            plan = module.plan_request("看看 Steam 库里有什么")
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertTrue(plan["steam_library_list_selected"])
        self.assertFalse(plan["needs_search"])
        self.assertEqual(plan["skill_route"], "none")
        self.assertFalse(plan["needs_balthasar"])
        self.assertEqual(model.call_count, 1)

    def test_ollama_router_error_unloads_compact_model_and_retries_with_ai(self):
        module = _load_melchior()
        recovered = {
            "response_mode": "RECOMMENDATION_RESEARCH",
            "needs_search": True,
            "research_depth": "recommendation_compare",
            "source_policy": "domain_evidence",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "standard",
            "research_profile": "recommendation_match",
            "recommendation_domain": "PRODUCT",
            "skill_route": "none",
            "reason": "product recommendation",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[RuntimeError("Ollama CUDA runner terminated"), recovered],
        ) as model, patch.object(module.tools, "unload_model") as unload:
            plan = module.plan_request("给我推荐几个吸管杯")
        self.assertEqual(plan["response_mode"], "RECOMMENDATION_RESEARCH")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "gemma3:4b",
        )
        self.assertEqual(model.call_args_list[0].kwargs["num_ctx"], 4096)
        self.assertTrue(model.call_args_list[0].kwargs["json_schema"])
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"],
            "gemma3:12b",
        )
        self.assertTrue(model.call_args_list[1].kwargs["json_schema"])
        unload.assert_called_once_with("gemma3:4b")

    def test_router_prompts_distinguish_content_destinations_from_user_folders(self):
        prompt_root = Path(__file__).resolve().parents[1] / "prompts"
        for name in ("melchior_router.txt", "melchior_router_recover.txt"):
            with self.subTest(prompt=name):
                text = (prompt_root / name).read_text(encoding="utf-8")
                self.assertIn("application-specific reusable content destination", text)
                self.assertIn("Downloads", text)
                self.assertIn("skill_route", text)

    def test_invalid_enum_dict_is_retried_instead_of_local_fallback(self):
        module = _load_melchior()
        invalid = {
            "response_mode": "LOCAL_ANSWER | DEVICE_ACTION",
            "reason": "schema echo",
        }
        recovered = {
            "response_mode": "DEVICE_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "reason": "local folder inspection",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[invalid, recovered, "OTHER"],
        ) as model, patch.object(module.tools, "unload_model") as unload:
            plan = module.plan_request("Downloads 文件夹里有什么？")
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertFalse(plan["needs_search"])
        self.assertGreaterEqual(
            model.call_args_list[0].kwargs["num_predict"],
            1200,
        )
        self.assertGreaterEqual(
            model.call_args_list[1].kwargs["num_predict"],
            1000,
        )
        unload.assert_called_once_with("gemma3:4b")

    def test_second_invalid_enum_raises_instead_of_using_stale_context(self):
        module = _load_melchior()
        invalid = {"response_mode": "LOCAL_ANSWER | DEVICE_ACTION"}
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[invalid, invalid],
        ), patch.object(module.tools, "unload_model") as unload:
            with self.assertRaises(RuntimeError):
                module.plan_request("Downloads 文件夹里有什么？")
        unload.assert_called_once_with("gemma3:4b")

    def test_content_action_gate_preempts_product_recommendation(self):
        module = _load_melchior()
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "medium",
            "complexity": "high",
            "reasoning_profile": "analytical",
            "skill_route": "lookup",
            "reason": "install game content",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[routed, "CONTENT_DEVICE_ACTION"],
        ) as model:
            plan = module.plan_request(
                "去网上找 FM26 战术并阅读教程整理安装方案"
            )
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertEqual(plan["complexity"], "high")
        self.assertTrue(plan["content_workflow_selected"])
        self.assertEqual(plan["skill_route"], "lookup")
        self.assertEqual(model.call_count, 2)
        self.assertGreaterEqual(model.call_args_list[0].kwargs["num_predict"], 1200)

    def test_complete_new_command_does_not_receive_stale_fm_context(self):
        module = _load_melchior()
        stale_context = (
            "User: 网上找一个最强 FM2026 战术并导入电脑\n"
            "Assistant: 正在寻找 Manchester United tactics"
        )
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "reason": "open recycle bin",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[routed, "RECYCLE_BIN_ACTION"],
        ) as model:
            plan = module.plan_request("打开回收站", stale_context)

        self.assertEqual(model.call_count, 1)
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertFalse(plan.get("content_workflow_selected", False))
        self.assertTrue(plan["recycle_workflow_selected"])
        self.assertEqual(plan["skill_route"], "none")

    def test_recycle_bin_scope_is_a_bounded_builtin_not_an_ai_widening(self):
        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=AssertionError("Recycle Bin must not call the content gate"),
        ) as model:
            result = module._classify_content_device_scope(
                "打开回收站",
                "User: 找一个最强 FM2026 战术并导入电脑",
            )
        self.assertEqual(result, "RECYCLE_BIN_ACTION")
        model.assert_not_called()

    def test_recycle_bin_overrides_ai_local_answer_and_companion(self):
        module = _load_melchior()
        raw = {
            "response_mode": "LOCAL_ANSWER",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "none",
            "interaction_mode": "COMPANION",
            "context_profile": "CONVERSATION",
            "reason": "opening trash can",
        }
        with patch.object(module.tools, "run_ai_prompt", return_value=raw):
            plan = module.plan_request("打开回收站")
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertTrue(plan["recycle_workflow_selected"])
        self.assertEqual(plan["interaction_mode"], "TASK")
        self.assertEqual(plan["context_profile"], "MINIMAL")
        self.assertFalse(plan["needs_balthasar"])
        self.assertEqual(plan["skill_route"], "none")

    def test_secondary_gate_cannot_widen_router_none_to_content_lookup(self):
        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=AssertionError("Router none must bypass the content gate"),
        ) as model:
            result = module._classify_content_device_scope(
                "打开记事本",
                "User: 之前安装过 FM26 战术",
                "none",
            )
        self.assertEqual(result, "OTHER")
        model.assert_not_called()

    def test_fm_tactics_folder_open_enters_skill_eligible_content_flow(self):
        module = _load_melchior()
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "low",
            "complexity": "low",
            "reasoning_profile": "quick",
            "skill_route": "lookup",
            "reason": "open local folder",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[routed, "CONTENT_DEVICE_ACTION"],
        ):
            plan = module.plan_request("打开 FM26 战术文件夹")
        self.assertTrue(plan["content_workflow_selected"])
        self.assertEqual(plan["skill_route"], "lookup")

    def test_referential_follow_up_keeps_recent_context_for_content_gate(self):
        module = _load_melchior()
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "medium",
            "complexity": "medium",
            "reasoning_profile": "standard",
            "skill_route": "lookup",
            "reason": "referential device action",
        }
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[routed, "CONTENT_DEVICE_ACTION"],
        ) as model:
            plan = module.plan_request(
                "那就安装那个",
                "User: 找一个 FM2026 战术",
            )

        gate_input = model.call_args_list[1].args[1]
        self.assertIn("FM2026", gate_input)
        self.assertTrue(plan["content_workflow_selected"])


if __name__ == "__main__":
    unittest.main()
