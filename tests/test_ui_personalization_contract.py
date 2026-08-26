import ast
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UiPersonalizationContractTests(unittest.TestCase):
    def test_root_and_casper_ui_mirrors_match(self):
        self.assertEqual(
            (PROJECT_ROOT / "ui.py").read_bytes(),
            (PROJECT_ROOT / "casper" / "ui.py").read_bytes(),
        )

    def test_ui_exposes_appearance_dialog_and_runtime_apply_method(self):
        tree = ast.parse((PROJECT_ROOT / "ui.py").read_text(encoding="utf-8"))
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        self.assertIn("AppearanceDialog", classes)
        window_methods = {
            node.name
            for node in classes["BekkiWindow"].body
            if isinstance(node, ast.FunctionDef)
        }
        self.assertIn("open_appearance_settings", window_methods)
        self.assertIn("apply_ui_preferences", window_methods)

    def test_preferences_are_stored_outside_chat_history(self):
        source = (PROJECT_ROOT / "ui_preferences.py").read_text(encoding="utf-8")
        self.assertIn('SETTINGS_FILE = DATA_DIR / "ui_preferences.json"', source)
        self.assertNotIn("chat_history.json", source)


if __name__ == "__main__":
    unittest.main()
