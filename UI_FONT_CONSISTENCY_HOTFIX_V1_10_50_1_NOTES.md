# UI Font Consistency Hotfix V1.10.50.1

Build ID: `bekki-bilibili-native-fact-executor-v1-10-51-3-20260903`

This hotfix keeps ordinary Chinese, English and mixed chat text at one visual
weight while preserving Bekki's intentional Markdown emphasis.

## Changes

- Every chat surface now uses the same explicit point size, Normal weight and
  ordered Latin/CJK font-family request.
- Qt context font merging is enabled when the installed PySide6 supports it,
  preventing a Chinese run from being assembled character by character from
  visually different fallback fonts.
- Ordinary messages render as safe plain text. Actual headings, emphasis,
  lists, code and links retain the existing safe Markdown path.
- Rich-text measurement and visible rendering now use the same font object,
  family chain, units and weight.
- The input editor and appearance preview use the same font builder.
- All previously size-less `QFont` objects in the appearance flow were removed,
  addressing the recurring `QFont::setPointSize ... (-1)` warning.

## Scope

No data, SQLite schema, Knowledge, Curiosity, routing, browser, search or model
behavior is changed. The installer preserves the complete installed `data`
directory and retains the existing rollback behavior.

## Manual check

After installation, run `python main.py`. The startup log should not contain
`QFont::setPointSize: Point size <= 0 (-1)`. Send the sentence printed by
`TEST_UI_FONT_CONSISTENCY_V1_10_50_1.ps1`; every ordinary Chinese glyph should
have a consistent weight, while the intentional Markdown phrase remains bold.
