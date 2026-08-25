# Bekki R8 shopping-query grounding repair

Build ID: `bekki-skills-v1-20260818-r8`

R8 keeps all R7 recommendation evidence and GPU protections, and fixes the
live planning failure reproduced by this request:

`给我推荐三个网红牌子杯子`

The compact planner incorrectly translated `网红牌子` first as Korean
celebrities and then as the invented search word `netred`. R7 correctly
failed closed before web search, but that left the user with zero cards.

R8 adds a bounded deterministic recovery after both AI plans fail:

- Python separates the agreed product category from popularity wording. It
  never selects or hardcodes a brand.
- Recovery is allowed only when primary and retry agree on the cleaned English
  category. A third 2K-context check by the same compact model must bind that
  category to an exact category phrase in the authoritative request and confirm that
  every explicit material, color, feature, use-case, size, and budget phrase is
  represented by the recovered query/requirements. Disagreement, a missing
  constraint, an added modifier, or an invalid check still fails closed.
- The same semantic check protects referential turns. An explicit category in
  the current request always wins over stale recent context; recent context may
  supply the category or a numeric/model-year constraint only when the current
  turn truly omits it and refers back.
- Python turns the structured popularity enum into executable regional search
  wording such as `cup viral trending brands 2026 United States`.
- Bad planner mappings such as `size <- 杯子`, `brand <- 网红`, and
  `normalized category <- 网红` cannot become product requirements.
- A real constraint is retained during recovery only when both AI attempts
  independently return the same source-owned, query-grounded constraint.
- Popularity words are masked before source ownership is checked, so the `红`
  inside `网红` cannot become a red-color constraint.
- Numeric constraints compare canonical currency, unit, and direction tokens:
  for example `$30` equals `30 dollars`, but `30美元以上` cannot become
  `under $30`, and `500克` cannot become `500 ml`.
- Chinese candidate counts such as `3个`, `3款`, `3双`, and `3台` are not
  mistaken for product specifications; real multipacks such as `3个装` and
  `3件套` remain hard constraints.
- Negated popularity wording such as `不要网红`, `不热门`, `unpopular`, or
  `anything but mainstream` cannot be reversed into a popularity requirement.
- Negated merchants and merchant comparisons do not become an accidental
  exclusive store lock. Exact positive requests such as `只在Amazon买` remain
  exclusive, while `不要Amazon` or `Amazon和Walmart比价` use a regional mix.
- Ordinary valid plans must bind every meaningful product-query token to a
  current-request requirement. Unrequested modifiers such as premium, ceramic,
  or large cannot become search or product requirements.
- The prompts explicitly define Chinese `网红品牌` as viral/trending consumer
  brands, never a celebrity, K-pop star, influencer person, or `netred`.

After installation, start from the project root with `python main.py` and
confirm:

`[BEKKI BUILD] bekki-skills-v1-20260818-r8`

Acceptance request:

`给我推荐三个网红牌子杯子`

The log should show `[SHOPPING PLAN REPAIR] grounded category consensus` only
when both compact AI attempts and the category check permit recovery. It should then continue into
search-engine and brand-evidence discovery instead of ending immediately with
`PLANNING_FAILED`. Live web evidence may still honestly produce fewer than
three cards or `NO_BRAND_POPULARITY_EVIDENCE`.
