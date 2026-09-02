import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UserMessageCompletenessV110416Tests(unittest.TestCase):
    def test_dynamic_bubble_has_width_and_wrap_safety(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        values = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "MESSAGE_BUBBLE_HORIZONTAL_CHROME",
                "MESSAGE_BUBBLE_NATURAL_WIDTH_SAFETY",
                "MESSAGE_BUBBLE_WRAP_WIDTH_SAFETY",
            }:
                values[target.id] = ast.literal_eval(node.value)

        self.assertGreaterEqual(values["MESSAGE_BUBBLE_NATURAL_WIDTH_SAFETY"], 12)
        self.assertGreaterEqual(values["MESSAGE_BUBBLE_WRAP_WIDTH_SAFETY"], 6)

        measure = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_measure_markdown_bubble"
        )
        measure_source = ast.unparse(measure)
        self.assertIn("MESSAGE_BUBBLE_NATURAL_WIDTH_SAFETY", measure_source)
        self.assertIn("MESSAGE_BUBBLE_WRAP_WIDTH_SAFETY", measure_source)
        self.assertIn("if dynamic_width else 0", measure_source)

    def test_user_safety_does_not_reduce_assistant_responsive_width(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("dynamic_width=self._is_user_message", source)
        self.assertIn("maximum_width=self._content_width", source)
        self.assertIn("MESSAGE_CONTENT_MAX_WIDTH = 760", source)

    def test_root_and_runtime_ui_are_identical(self):
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
