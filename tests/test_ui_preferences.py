import json
import tempfile
import unittest
from pathlib import Path

import ui_preferences


class UiPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_missing_file_uses_safe_defaults(self):
        result = ui_preferences.load_preferences(self.root / "missing.json")
        self.assertEqual(result["font_family"], "Segoe UI Variable")
        self.assertEqual(result["font_size"], 13)
        self.assertEqual(result["avatar_path"], "")

    def test_font_size_is_clamped_and_saved_atomically(self):
        path = self.root / "ui_preferences.json"
        result = ui_preferences.save_preferences(
            {"font_family": "Microsoft YaHei UI", "font_size": 99},
            path,
        )
        self.assertEqual(result["font_size"], 20)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["font_family"], "Microsoft YaHei UI")
        self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_custom_avatar_is_copied_into_persistent_data(self):
        source = self.root / "source.png"
        source.write_bytes(b"fake-png-for-copy-contract")
        destination = ui_preferences.persist_avatar(
            source,
            self.root / "data",
        )
        self.assertEqual(Path(destination).read_bytes(), source.read_bytes())
        self.assertEqual(Path(destination).name, "bekki_custom_avatar.png")

    def test_invalid_avatar_type_is_rejected(self):
        source = self.root / "avatar.exe"
        source.write_bytes(b"not-an-image")
        with self.assertRaisesRegex(ValueError, "avatar_type_not_supported"):
            ui_preferences.persist_avatar(source, self.root / "data")


if __name__ == "__main__":
    unittest.main()
