# Bekki R12 recommendation-versus-shopping boundary

Build ID: `bekki-skills-v1-20260818-r12`

R12 fixes the failure reproduced after R11 with:

`给我推荐三个杯子`

R11 routed the request correctly but then treated a recommendation as a
shopping task. It discovered merchants, opened product-detail pages, checked
stock, and returned zero cards when those purchase listings were unsuitable.
The user had asked what was worth recommending, not where to buy it.

R12 separates the two product routes system-wide:

- `RECOMMENDATION_RESEARCH` reads independent reviews, comparisons, and
  recommendation roundups, extracts exact visible products or brands, and
  returns editorial recommendation cards.
- It never calls merchant discovery or product-detail verification and never
  claims current price, stock, seller, or purchase availability.
- `SHOPPING_RESEARCH` remains the purchase route and is used only for explicit
  buy, price, stock, seller, ordering, or purchase-link intent.
- An optional browser AI may help discover or summarize sources, but its output
  is only a lead; Bekki opens the cited original public source before using it.
- Zero-evidence replies now describe missing review/recommendation evidence
  instead of telling a recommendation-only user to choose a shopping site.

Acceptance requests:

- `给我推荐三个杯子` must use independent recommendation sources and must not
  log verified merchants or product-page reads.
- `查一下这个杯子的价格和库存` must continue through verified product pages.
