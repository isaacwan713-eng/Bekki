# Bekki R13 recommendation count and grounded reply repair

Build ID: `bekki-skills-v1-20260818-r13`

R13 fixes the R12 result reproduced by:

`给我推荐三个杯子`

R12 correctly stayed on independent review and recommendation pages, but its
compact extractor returned one item and stopped even though six sources had
been opened. The final reply then freely added unsupported descriptions such
as "very popular", "durable", and "elegant".

R13 applies a hybrid quantity rule:

- An explicit user count is authoritative. Casper scans all opened editorial
  sources and makes up to two bounded additional extraction passes for missing
  distinct candidates.
- Returning fewer remains valid when the source evidence genuinely cannot
  support the requested count; no candidate is invented merely to fill a slot.
- If the user does not specify a count, the compact AI chooses one to three
  useful evidence-backed recommendations without forced padding.
- Shopping/search subdomains are excluded from the independent editorial
  evidence set.
- The visible reply is rendered from validated product names, source domains,
  and exact recommendation labels such as best overall or top pick. The final
  model no longer gets an opportunity to invent unsupported product traits.

The R12 recommendation-versus-shopping boundary remains unchanged: ordinary
recommendations never enter merchant or product-detail pages.
