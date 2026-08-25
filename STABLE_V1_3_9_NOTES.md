# Bekki Stable V1.3.9

Build ID: `bekki-stable-v1-3-9-20260824`

This update changes only the social-research evidence and recommendation path.
The stable R25 UI and ordinary SEARCH / LOCAL / COMMAND behavior are unchanged.

## Xiaohongshu recommendation flow

- Retains and briefly describes up to seven recent, date-validated posts.
- Opens up to seven title-bound post pages for grounded details.
- Reads likes, comments, and shares only when both the visible value and its
  label are present in the same post evidence.
- Ranks usable post cards by the total visible interactions and returns no more
  than three.
- Returns one or two cards when only one or two posts have usable interaction
  evidence; it never invents enough posts to reach three.
- May use an unlabeled search-grid interaction value as a fallback ranking
  signal, but never labels that value as likes, comments, or shares.
- Preserves restaurant names exactly as written. Missing images or links are
  acceptable and are not filled with unrelated content.

## Validation

The regression suite includes coverage for seven-post extraction, bounded
three-call detail batching, same-post metric evidence validation, Chinese and
English count suffix parsing, Top 3 ordering, and fewer-than-three behavior.
