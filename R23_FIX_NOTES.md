# Bekki R23 exact-product purchase lookup

Build ID: `bekki-skills-v1-20260818-r23`

R23 separates two shopping intents that previously shared one restrictive
pipeline:

- Exact-product purchase lookup answers where one already identified product
  can be bought.
- Open-ended shopping comparison continues to discover and compare options.

The 12B AI owns the semantic split and resolves references such as `第一个` from
recent conversation. An exact lookup must copy a complete brand/model title
from the declared source; Python checks only that binding and the output shape.
The target can no longer collapse from `Simple Modern Classic Tumbler` to the
generic word `tumbler`.

Exact lookup searches Google first with Bing as the cached fallback. Search AI
summaries are leads only. One AI proposes likely official or retailer purchase
entries and an independent adversarial AI audits exact identity, merchant
reality, and direct purchase intent. Accessories, replacement parts, different
models, generic category pages, articles, and social posts are rejected.

Price and stock are optional. When not visible, the card keeps `UNKNOWN`
instead of dropping an otherwise valid where-to-buy result. A candidate page is
opened only when the audit requests more evidence, and at most once.

The exact path skips recommendation popularity checks, independent review
roundups, merchant-wide comparison, multi-product scoring, and unrelated
feature gates. It uses `gemma3:12b`; the 20B model is unloaded before browsing.
