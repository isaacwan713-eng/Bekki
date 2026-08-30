# Knowledge Correction V1.10.4

Build: `bekki-knowledge-correction-v1-10-4-20260829`

This release closes three failures observed in the V1.10.3 real run.

## Knowledge durability

- Every mixed-answer lifecycle result containing a persisted `stable` claim
  now receives a final independent Gemma 4 durability critique, even when the
  first partitioner and lifecycle auditor agreed.
- Maintained current structures and official unit inventories are
  `reviewable`; durable definitions and mechanisms may remain `stable`;
  current people, affiliations, rosters, schedules, prices, and events remain
  current-turn-only.
- The runtime triggers and validates the AI contract without embedding entity,
  topic, or organization-name rules in Python.
- Existing V2 mixed-answer records are selected for V3 idle re-audit. No user
  Knowledge is deleted during migration.

## User corrections

- A local AI distinguishes public objective disputes from corrections about
  the user's own identity, family, household, devices, accounts, routines, or
  preferences.
- Personal corrections remain local and user-authoritative.
- A public correction marks only the exact AI-selected Knowledge record as
  `disputed`, immediately excluding it from recall while Bekki independently
  rechecks the fact.
- The user's proposed correction is a research trigger, not evidence.
- Reverification can refresh the same record, supersede it with an exact new
  reusable record, or leave the old record inactive when evidence is
  inconclusive or current-turn-only.
- Old claim text and lifecycle metadata remain in bounded `revision_history`.

## Search semantics

- Query audits preserve distinctive source-language taxonomy when a confident
  exact translation is unavailable. A cohort term may not silently become a
  trainee or employment status.
- Evidence-gap follow-up queries may each target one missing facet. The AI
  audits them together as a query set, instead of requiring each focused query
  to repeat the complete original multi-part request.
- The same AI-owned entity, hierarchy, temporal, and translation boundaries
  still apply to every focused query.

## Verification

The deterministic suite contains targeted contracts for unanimous-but-wrong
`stable` labels, V2 migration, correction history and replacement linking,
personal versus public authority, source-term preservation, and focused
follow-up query sets.

Run the real-model contracts after installation:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v `
  tests.test_live_ai_contracts.LiveAIContractTests.test_mixed_claim_lifecycle_audit_contract `
  tests.test_live_ai_contracts.LiveAIContractTests.test_query_translation_and_focused_follow_up_contract `
  tests.test_live_ai_contracts.LiveAIContractTests.test_knowledge_correction_authority_contract
```

Then start Bekki with `python main.py`. Existing `.env`, `data`, `.git`,
virtual environments, build output, and browser profiles remain protected by
the installer.
