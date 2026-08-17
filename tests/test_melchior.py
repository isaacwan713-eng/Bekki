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
            side_effect=[invalid, recovered],
        ):
            plan = module.plan_request("Downloads 文件夹里有什么？")
        self.assertEqual(plan["response_mode"], "DEVICE_ACTION")
        self.assertFalse(plan["needs_search"])

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


if __name__ == "__main__":
    unittest.main()
