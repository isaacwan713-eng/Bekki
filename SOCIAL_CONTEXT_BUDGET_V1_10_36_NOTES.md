# Social Context Budget V1.10.36

## Observed failure

Bilibili first-load recovery succeeded, produced 30 candidates, selected five
posts, and opened all five real detail pages. The optional post-introduction
prompt then contained 8519 tokens, exceeding the 8192-token Gemma context.
Casper discarded the already-completed research and incorrectly surfaced the
failure as an unavailable Ollama connection.

## Bounded enrichment contract

- The model context remains 8192 for practical RTX 5080 16 GB headroom while a
  foreground game is open.
- Each introduction call contains no more than two posts and two screenshots.
- Search-card text is capped at 500 characters per post.
- Opened-page text is capped at 1300 characters per post.
- The user request is capped at 500 characters for this enrichment stage.
- Introduction output is capped at 1200 tokens.
- One failed batch is skipped without failing other batches.
- An unexpected introduction-stage exception falls back to existing evidence.
- Titles, authors, dates, interaction counts, real URLs, images, summaries,
  direct replies, and cards remain available without optional introductions.

No model, search provider, AI role, or arbitration gate was added.
