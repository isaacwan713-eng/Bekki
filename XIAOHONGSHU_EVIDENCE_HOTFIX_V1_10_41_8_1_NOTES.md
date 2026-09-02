# Xiaohongshu Evidence Hotfix V1.10.41.8.1

- Treats the visible publication time in the opened Xiaohongshu note as the
  authoritative date. English month labels such as `Feb 22` and Chinese
  relative labels such as `4天前` are resolved against the runtime date.
- Reports and corrects search/detail date conflicts. A detail-authoritative
  date outside a requested RECENT window removes the post rather than allowing
  a misleading current date into the answer or card.
- Adds a structured hard scope gate over entity, requested category, and the
  relation that makes the result relevant. Search placement or a related-post
  shelf is never relevance evidence by itself.
- Allows bounded substitutions only when the request's core relation and
  category survive: a slightly larger insulated cup can satisfy a cup search,
  and another aespa member's Nongshim photocard can satisfy an aespa Nongshim
  photocard search.
- Excludes semantically adjacent but unusable results, including a generic
  Winter photocard with no Nongshim connection and a plush keychain in a
  photocard search. Excluded posts cannot re-enter through summaries, cards,
  rankings, or synthesis.
- Downloads the best available Xiaohongshu media candidate and rejects blurred,
  low-information, black, placeholder, and duplicate rasters. A sharp page
  shell around blurred content no longer passes the image check.
- Detects native Xiaohongshu video notes and captures up to two distinct,
  non-black frames from the actual player. Generic full-page screenshots are
  not used as video evidence.
- Keeps old social-card fallback behavior when no opened-detail evidence exists
  and includes Discussion Feed V1.10.41.8 plus all earlier fixes.
