# Social Evidence Binding V1.10.41.3

Build: `bekki-social-evidence-binding-v1-10-41-3-20260901`

This patch keeps every social summary, screenshot and source link bound to the
same resolved post while reducing unnecessary local vision work.

## Fixed

- Xiaohongshu detail understanding now reads the current note's title and
  description container. Related-note shelves and platform navigation are not
  accepted as the opened note body; an unscoped detail page falls back to its
  explicitly labeled search preview.
- Search-page overview vision is deferred until post resolution. If any
  title-bound post screenshot exists, the overview call is skipped in all
  ranking modes. If no post screenshot exists, the previous overview fallback
  remains available.
- When at least one post has been resolved, only resolved titles enter model
  introductions, final summaries and result cards. Plain search suggestions
  without a post URL or result image are not clicked as posts.
- Repeated OCR/model output such as the same short card label repeated three or
  more times is collapsed before prompt reuse and display.
- Social cards now retain `evidence_level` and distinguish a concrete post link
  from a platform search-page fallback. The UI says `打开原帖` for the former
  and `查看搜索页` for the latter.

## Runtime budget

- `gemma4:12b` remains the social understanding model.
- Social model context remains `8192` tokens.
- Xiaohongshu retains up to three original post images plus one body capture;
  Reddit retains one post-body capture.
- No additional model call or browser profile is introduced.
- The persistent minimized unified browser profile and 16 GB VRAM coexistence
  target are unchanged.

## Suggested Windows checks

1. Search Xiaohongshu for an `aespa LEMONADE` image guide containing related
   recommendations. Each card summary should describe only its own note.
2. Confirm the log prints `SOCIAL VISUAL OVERVIEW SKIPPED` when post-bound
   screenshots exist, without a search-page visual-model call.
3. Confirm repeated labels are rendered once with `重复项已省略`.
4. Confirm a concrete note uses `打开原帖`, while an unavoidable search-page
   fallback uses `查看搜索页` and remains labeled as a search preview.
