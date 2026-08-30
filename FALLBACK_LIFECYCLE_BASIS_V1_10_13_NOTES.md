# Fallback Lifecycle Basis V1.10.13

Build: `bekki-fallback-lifecycle-basis-v1-10-13-20260829`

## Corrected standalone fallback lifecycle

- The existing External Fact Governor and independent policy auditor now
  select an explicit `lifecycle_basis` before `knowledge_type`.
- A present complete list of formal teams, departments, branches, provisions,
  standards, or classifications is `MAINTAINED_SET_OR_STRUCTURE`.
- The words `current`, `currently`, `目前`, and an as-of date do not make that
  formal-unit set current-turn-only.
- People rosters, one person's current affiliation, schedules, prices, scores,
  versions, availability, and events remain
  `TRANSIENT_CURRENT_STATE_OR_EVENT` and do not enter Knowledge.
- The authoritative request overrides any generated fact-scope facet that
  accidentally broadens a unit-list question into member assignments or
  per-unit operating status.

## AI ownership and persistence

- No AI role, gate, arbiter, or normal-path model call was added.
- Python checks only whether the AI-selected basis, lifecycle type, and review
  interval agree; it contains no organization, language, or team keyword map.
- Standalone low-impact stable or reviewable facts retain the audited basis in
  Knowledge for later scheduled or randomized lifecycle review.

## Focused real-model test

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_current_formal_unit_set_fallback_lifecycle_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```

Expected lifecycle:

```text
decision=ASK
importance=LOW
lifecycle_basis=MAINTAINED_SET_OR_STRUCTURE
knowledge_type=stable or reviewable
has_reusable_component=false
```
