# Unified Result Blocks V1.10.41

Build: `bekki-unified-result-blocks-v1-10-41-20260901`

## What changed

- The main Bekki reply contains only the overall conclusion or cross-result
  synthesis when structured result cards are present.
- Recommendation-specific explanations and supported pros/cons are bound to
  the exact matching candidate card.
- Social post-specific findings are bound to the matching post card, including
  cards whose visible title is a restaurant or product name.
- Every result remains one ordered evidence block: context, matching image or
  explicit image placeholder, then matching source link.
- The full and lightweight final prompts now apply the same non-duplicating
  card-first contract to ordinary search, recommendation search, and social
  research.

## Runtime budget

This patch does not increase the social model context, image limits, or model
size. Social synthesis remains bounded to an 8192-token context and retains the
existing 16 GB GPU coexistence target.

## Suggested test

Ask Bekki to recommend three products with several constraints. The expected
layout is one short overview followed by three cards. Each card should contain
only that product's explanation and tradeoffs, its image or placeholder, and
its own source link; the overview should not repeat the three product names.
