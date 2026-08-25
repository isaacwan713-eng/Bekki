# Bekki Stable V1.3.6

Build: `bekki-stable-v1-3-6-20260824`

This release fixes the live case where evidence named a restaurant
`Beijing Tasty House`, but the final answer invented the unsupported Chinese
name `北京外婆家`.

- Candidate names are copied exactly from evidence and remain in their source
  language.
- Names may not be translated, transliterated, localized, shortened, or
  replaced with an invented another-language name.
- UNKNOWN suitability remains unverified in the final wording.
- When fewer candidates are verified than the user requested, Bekki states the
  verified count instead of pretending that the target was met.
- Recommendation search, MAGI routing, cards, and the stable UI are unchanged.
