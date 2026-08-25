# Bekki R18 verified recommendations and cached runtime profile

Build ID: `bekki-skills-v1-20260818-r18`

R18 addresses two live R17 findings.

First, R17 could discover two products from editorial sources but both were
children's trainer cups, and one was a soft-spout cup rather than a verified
straw cup. Recommendation research is now two-stage:

1. Gemma discovers exact candidates from search summaries, overview-like
   snippets, and opened independent reviews.
2. Gemma creates candidate-specific follow-up queries.
3. Casper reads non-merchant verification sources for each candidate.
4. Gemma checks the exact requested category, every explicit condition, and
   the AI-decided audience scope.
5. Failed or unverified candidates are removed. When too few remain, Gemma
   creates one bounded recovery search and verifies the new candidates.
6. The final reply is written only from candidates that passed verification.

For `吸管杯`, a soft-spout trainer cup no longer passes without evidence of a
straw. For `不锈钢吸管杯`, both the straw-cup category and stainless-steel
condition must be supported. Python executes AI-created queries and binds cited
source indexes; it does not implement a product-category keyword catalog.

Second, the live R17 request still invoked `gemma3:12b` for Melchior routing
and hit Windows `0xc0000409` / CUDA shared-object initialization failure before
the browser started. Routine authoritative routing now uses `gemma3:12b`.
The 20B model remains reserved for deep conversation, learning, and larger
reasoning work.

R18 also adds `data/location.json`, created on first startup and refreshed after
seven days or a system time-zone/offset change. It caches country, time zone,
unit system, currency, and preferred search engines. A US Windows profile uses
US customary units plus Google/Bing. The compact JSON is injected into routing
and reply prompts; fresh engine defaults bypass per-query engine-planning AI.
Explicit current-turn location, unit, or engine instructions override the cache
for that turn without silently rewriting the persistent default.

Expected recommendation logs include:

- `[BEKKI RUNTIME PROFILE]`
- `[CASPER AI RECOMMENDATION PLAN]`
- `[CASPER RECOMMENDATION SOURCE]`
- `[CASPER RECOMMENDATION VERIFY SOURCE]`
- `[CASPER RECOMMENDATION VERIFIED]`
- optional `[CASPER RECOMMENDATION RECOVERY QUERIES]`
- `[CASPER AI RECOMMENDATION OPTIONS]`

Known merchant product pages and the shopping planner remain absent unless the
user explicitly asks to buy, check price/stock, locate a seller, or get a
purchase link.
