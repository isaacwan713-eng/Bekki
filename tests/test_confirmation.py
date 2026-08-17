import ast
import json
import re
from pathlib import Path
import unittest
from unittest.mock import Mock


def load_confirmation_function(model):
    source = Path(__file__).parents[1].joinpath("tools.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "is_confirmation"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"json": json, "re": re, "run_ai_prompt": model}
    exec(compile(module, "tools.py", "exec"), namespace)
    return namespace["is_confirmation"]


class ConfirmationTests(unittest.TestCase):
    def test_explicit_device_confirmation_bypasses_ai(self):
        model = Mock(return_value="CONFIRM")
        classify = load_confirmation_function(model)
        self.assertTrue(
            classify(
                "继续",
                {"type": "device_action_approval", "original_request": "打开原神"},
                "",
            )
        )
        self.assertEqual(model.call_count, 0)

    def test_non_explicit_device_reply_still_uses_ai(self):
        model = Mock(side_effect=["", "CONFIRM"])
        classify = load_confirmation_function(model)
        self.assertTrue(
            classify(
                "我想了一下，还是照刚才的方案处理",
                {"type": "device_action_approval", "original_request": "打开原神"},
                "",
            )
        )
        self.assertEqual(model.call_count, 2)

    def test_two_invalid_ai_outputs_do_not_confirm_ambiguous_reply(self):
        model = Mock(side_effect=["", ""])
        classify = load_confirmation_function(model)
        self.assertFalse(
            classify(
                "再看看",
                {"type": "device_action_approval", "original_request": "打开原神"},
                "",
            )
        )

    def test_continue_without_device_approval_does_not_bypass_ai(self):
        model = Mock(return_value="NOT_CONFIRM")
        classify = load_confirmation_function(model)
        self.assertFalse(classify("继续", {"type": "search"}, ""))
        self.assertEqual(model.call_count, 1)


if __name__ == "__main__":
    unittest.main()
