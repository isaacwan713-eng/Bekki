# Bekki Stable V1.3.7

Build: `bekki-stable-v1-3-7-20260824`

This release fixes the live follow-up case where “which of these three” first
resolved the prior restaurants correctly, but query review reopened the search
and replaced two of them with new candidates.

- The recommendation planning AI returns OPEN or FIXED candidate scope.
- FIXED scope names must be copied exactly from recent context.
- Python validates that every fixed name is grounded in the visible request or
  recent context, then keeps queries, extraction, retries, and selection inside
  that closed set.
- Missing evidence produces fewer cards or UNKNOWN caveats; it never causes a
  substitute restaurant.
- Restaurant names use opaque final-writing tokens and are restored from card
  titles after JSON parsing, preventing partial translation.
- Search safety, MAGI routing, and the stable UI are unchanged.
