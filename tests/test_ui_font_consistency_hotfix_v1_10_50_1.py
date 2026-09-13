from pathlib import Path
import unittest

import message_markdown


ROOT = Path(__file__).resolve().parents[1]


class UiFontConsistencyHotfixV110501Tests(unittest.TestCase):
    def test_plain_multilingual_chat_stays_on_plain_text_path(self):
        value = (
            '去 B 站查一下虚拟主播组合“四喜丸子”。如果名字写错了，'
            '请根据官方账号纠正。Official source only。'
        )
        self.assertFalse(message_markdown.has_rich_markdown(value))

    def test_visible_markdown_still_uses_rich_rendering(self):
        for value in (
            "**重点**",
            "- 第一项\n- 第二项",
            "[官方来源](https://example.com)",
            "`relationship_id`",
        ):
            with self.subTest(value=value):
                self.assertTrue(message_markdown.has_rich_markdown(value))

    def test_ui_uses_one_explicit_font_contract(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def build_ui_font(", source)
        self.assertIn("font.setFamilies(_chat_font_family_chain(family))", source)
        self.assertIn("font.setPointSize(point_size)", source)
        self.assertIn("font.setWeight(weight or QFont.Weight.Normal)", source)
        self.assertIn('"ContextFontMerging"', source)
        self.assertIn("PreferVerticalHinting", source)
        self.assertIn("Qt.RichText if rich_text else Qt.PlainText", source)
        self.assertIn("document.setPlainText", source)
        self.assertNotIn("QFont(family, size)", source)
        self.assertNotIn('QFont(self._original["font_family"])', source)

    def test_chat_css_uses_point_size_and_explicit_normal_weight(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn("font-size: {size}px;", source)
        self.assertGreaterEqual(source.count("font-size: {size}pt;"), 2)
        self.assertGreaterEqual(source.count("font-weight: 400;"), 4)

    def test_application_font_is_never_created_with_an_unset_size(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            'app.setFont(build_ui_font("Segoe UI Variable", 10))',
            source,
        )
        self.assertNotIn("from PySide6.QtGui import QFont", source)

    def test_build_preserves_font_parent_and_sqlite_foundation(self):
        import json

        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Legacy Visual Evidence Backfill V1.10.54.8",
        )
        self.assertEqual(
            metadata["baseline"],
            "SQLite Knowledge + NERV Storage Phase 2 V1.10.49",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )

    def test_runtime_mirrors_remain_exact(self):
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "message_markdown.py").read_bytes(),
            (ROOT / "casper" / "message_markdown.py").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
