# Bekki R7 recommendation evidence and GPU recovery patch

Build ID: `bekki-skills-v1-20260818-r7`

R7 fixes the product-recommendation failures reproduced after R6:

- A complete new shopping request is isolated from earlier products, prices,
  constraints, and profile state. Explicit follow-ups receive only bounded
  recent text needed to resolve their reference.
- `网红`, trending, mainstream, well-known, popular, and best-selling intent is
  preserved as a structured requirement instead of being weakened to generic
  quality wording.
- Explicit popularity claims require brand names grounded in multiple distinct
  current publisher domains. Each source must visibly bind that same brand to
  positive trending/mainstream/demand language; a mere mention, old trend, or
  another subdomain does not count. Merchant pages then verify the actual
  product, price, stock, rating, and review evidence.
- Product selection is deterministic, requirement-aware, and brand-diverse.
  Unknown niche brands never fill missing slots merely to produce three cards.
- Brand and merchant searches are round-robin, and the six-page extraction
  budget preserves candidates from each verified brand. Unknown merchant
  domains need visible Product JSON-LD before a page can become a product card.
- The search-engine catalog is filtered to the detected region before planning.
  Engine planning uses only the compact model, catches model errors, and reuses
  one eligible plan throughout a shopping request.
- A failure in one search engine or one product extraction no longer erases
  results already verified from other sources.
- Shopping extraction is bounded to six candidates at an 8K context instead of
  repeatedly requesting a 32K large-model context. Bekki unloads the inactive
  model at planning/extraction boundaries on a best-effort basis.

After installation, start from the project root with `python main.py` and
confirm:

`[BEKKI BUILD] bekki-skills-v1-20260818-r7`

Acceptance requests in one session:

1. `给我推荐三个杯子`
2. `给我推荐三个网红牌子杯子`

The second request must not inherit product names, prices, budgets, or features
from the first. It must return distinct brands supported by current evidence, or
an honest partial/no-results response. It must never fill three slots with
unverified niche brands. The console must not repeatedly switch to `gpt-oss`
for search-engine planning.
