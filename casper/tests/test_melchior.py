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
        "tools": types.SimpleNamespace(run_ai_prompt=lambda *_a, **_k: None),
        "vision": types.SimpleNamespace(has_image=lambda: False),
    }
    path = Path(__file__).resolve().parents[1] / "melchior.py"
    spec = importlib.util.spec_from_file_location("melchior_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class MelchiorRecoveryTests(unittest.TestCase):
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
        ) as model:
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

    def test_second_invalid_enum_raises_instead_of_using_stale_context(self):
        module = _load_melchior()
        invalid = {"response_mode": "LOCAL_ANSWER | DEVICE_ACTION"}
        with patch.object(
            module.tools,
            "run_ai_prompt",
            side_effect=[invalid, invalid],
        ):
            with self.assertRaises(RuntimeError):
                module.plan_request("Downloads 文件夹里有什么？")

    def test_content_action_gate_preempts_product_recommendation(self):
        module = _load_melchior()
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "medium",
            "complexity": "high",
            "reasoning_profile": "analytical",
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

        self.assertEqual(model.call_count, 2)
        scope_input = model.call_args_list[1].args[1]
        self.assertLess(
            scope_input.index("打开回收站"),
            scope_input.index("FM2026"),
        )
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertFalse(plan.get("content_workflow_selected", False))
        self.assertTrue(plan["recycle_workflow_selected"])
        self.assertEqual(plan["skill_route"], "none")

    def test_recycle_bin_scope_is_decided_by_ai_not_python_keywords(self):
        module = _load_melchior()
        with patch.object(
            module.tools,
            "run_ai_prompt",
            return_value="RECYCLE_BIN_ACTION",
        ) as model:
            result = module._classify_content_device_scope(
                "打开回收站",
                "User: 找一个最强 FM2026 战术并导入电脑",
            )
        self.assertEqual(result, "RECYCLE_BIN_ACTION")
        model.assert_called_once()
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")
        self.assertGreaterEqual(model.call_args.kwargs["num_predict"], 256)

    def test_referential_follow_up_keeps_recent_context_for_content_gate(self):
        module = _load_melchior()
        routed = {
            "response_mode": "DEVICE_ACTION",
            "risk": "medium",
            "complexity": "medium",
            "reasoning_profile": "standard",
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
