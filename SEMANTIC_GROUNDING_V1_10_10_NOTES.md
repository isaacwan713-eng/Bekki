# Semantic Grounding V1.10.10

Build: `bekki-semantic-grounding-v1-10-10-20260829`

This release strengthens existing AI contracts without adding an AI role,
gate, arbiter, or normal-path model call.

- Source expressions are marked `USER_ESTABLISHED` or
  `OPEN_RESEARCH_TARGET`. Open or uncertain terms stay verbatim in search
  queries; mixed-language retrieval is valid.
- Query audit and certification explicitly report whether every open source
  boundary was preserved without an asserted translation.
- Mixed-claim lifecycle audit V5 makes the existing AI select a semantic basis
  before its lifecycle label. Storage accepts only internally consistent
  basis/type/expiry decisions.
- The Daily Curator grounds subjects in literal claim wording, separates nearby
  hierarchy levels, and records claim-language evidence for relationships.
- Reviewable knowledge expires pending separate re-verification; it is not
  silently refreshed. A user dispute can invalidate it sooner.

Validation: 806 deterministic tests passed; 14 live Ollama smoke tests remain
opt-in through `BEKKI_LIVE_AI_TESTS=1`.
