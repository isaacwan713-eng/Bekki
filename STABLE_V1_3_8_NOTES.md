# Bekki Stable V1.3.8

Build: `bekki-stable-v1-3-8-20260824`

This release fixes the remaining live fixed-candidate comparison failures.

- A rendered source page must literally contain a fixed restaurant's exact
  name before it can produce evidence for that restaurant.
- Unrelated pages such as people lists, movie guides, login pages, and event
  schedules cannot manufacture fixed-candidate summaries.
- Candidate selection keeps one best evidence record for every fixed name and
  cannot silently drop the third restaurant.
- If a fixed candidate has no current source, it remains in the comparison with
  explicit UNKNOWN evidence rather than disappearing or being substituted.
- The comparison AI may make a clearly qualified practical family-dining
  judgment from candidate-specific menu, dish, service, seating, atmosphere,
  and prior-turn evidence. It may not turn that inference into a verified
  high-chair, accessibility, or child-policy claim.
- Exact restaurant-name placeholders now cover the entire fixed set, not only
  the candidates that happened to receive clickable cards.
- Search safety, MAGI routing, and the stable UI are unchanged.
