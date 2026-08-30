# Nonstructural Lifecycle Boundary V1.10.14

Build: `bekki-nonstructural-lifecycle-v1-10-14-20260829`

## Problem

For `SNH48目前有哪些正式Team？`, both existing fallback lifecycle AIs
treated the word `目前` as sufficient evidence for a transient current state.
The upstream research scope also added an unrequested facet about each team's
current status, and the second AI could see and repeat the first AI's complete
lifecycle proposal.

## Changes

- The standalone fallback transient basis is now
  `TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT`. It covers current people,
  affiliations, rosters, schedules, prices, scores, versions, availability,
  and events—not maintained formal-unit sets.
- A maintained official set may still be `stable` or `reviewable`, according
  to AI judgment. `CURRENT_ACTIVE_STATE` controls evidence freshness only.
- Lifecycle AIs receive the authoritative user request plus bounded retrieval
  time metadata. Browser-generated entity facets cannot broaden the semantic
  subject.
- The existing independent policy auditor receives only the first Governor's
  sharing preview. It no longer sees the first lifecycle label, basis,
  interval, reusable-component flag, or reason.
- The mixed-answer partition lifecycle remains backward compatible with its
  established basis vocabulary.

No third AI, keyword classifier, domain-specific SNH48 rule, or additional
model call was added.

## Focused live test

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_current_formal_unit_set_fallback_lifecycle_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```
