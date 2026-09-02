# Bekki Markdown Evidence V1.10.40

Build ID: `bekki-markdown-evidence-v1-10-40-20260901`

## What changed

- Every user and Bekki chat bubble now renders a bounded safe-Markdown subset:
  paragraphs, headings, lists, emphasis, inline code, tables, and HTTPS links.
- JSON remains the model/runtime transport. Only the visible `reply` string is
  Markdown, so this release does not weaken structured-output validation.
- Every sourced result is an ordered, self-contained evidence block:
  `context -> image/placeholder -> matching link`.
- Ordinary web-search sources now use the same evidence component as news,
  recommendations, shopping results, places, and social posts.
- Recommendation context retains candidate-specific price, brand, match score,
  popularity evidence, requirement matches, facts, and pros/cons when present.
- URLs already represented by a richer result card are removed from the plain
  source list, preventing duplicate or detached links.
- Raw HTML, Markdown image embedding, local/data/executable links, and unsafe
  external navigation are not accepted in chat Markdown.
- Existing plain-text chat history remains valid and is upgraded to history
  schema 6 with `content_format: markdown`.
- V1.10.39 media limits are preserved: a Xiaohongshu evidence block may contain
  its first three post images plus one body-text capture; Reddit retains one
  post-body capture. Non-social source and recommendation blocks display one
  image each.
- The local model, `num_ctx=8192`, browser login profile, and background browser
  behavior are unchanged.

## Suggested Windows checks

1. Ask a local question containing a Markdown heading, list, bold text, inline
   code, and a table; confirm the bubble renders them instead of showing syntax.
2. Run an ordinary web search with two sources; confirm the UI shows source 1's
   context, image/placeholder, and link before source 2 begins.
3. Run a recommendation search with two candidates; confirm each candidate's
   explanation, image, constraints, and link remain in the same block.
4. Reopen an older conversation and confirm its plain messages still render.
5. Run Xiaohongshu and Reddit checks to confirm the V1.10.39 screenshot limits
   and original-post links remain unchanged.

## Validation

- `python -m unittest discover -s tests -p 'test_*.py'`
- 995 tests passed; 28 platform/environment-dependent tests skipped.
- `python -m py_compile` for all root and Casper Python modules.
