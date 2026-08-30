# Language-Safe Knowledge Review V1.10.11

Build: `bekki-language-safe-review-v1-10-11-20260829`

## Language-safe retrieval

- Translation preservation is language-neutral. Any expression without a safe
  exact equivalent remains verbatim in the retrieval query.
- Ordinary fact lookup may use a mixed-language query and still completes the
  normal bounded 3-5-7 search before External AI fallback.
- Social search never translates meaningful user search expressions. It may
  remove only the platform/command wrapper and redundant wording.
- Open research terms use `established_equivalent: null`; the scope planner may
  not pre-answer their meaning by inventing a gloss.
- Python validates structured AI output only. It has no vocabulary list,
  language classifier, SNH48 rule, or social-platform translation rule.

## Knowledge lifecycle

- One lifecycle AI owns the semantic decision. A second call is permitted only
  to recover malformed or internally inconsistent output; the former final
  stability critic is removed.
- A maintained set or organizational structure may be either `stable` or
  `reviewable`. Both are accepted when the stated lifecycle basis is
  proportional.
- Individual current affiliations, rosters, events, schedules, and similar
  transient states remain `changing` and are not persisted.

## Random stable review

- Stable knowledge has no fixed expiry, but it is not treated as permanently
  unquestionable.
- During idle time, Bekki samples at most one eligible stable record per local
  day. Maintained structures have higher sampling weight than fixed historical
  facts and durable mechanisms.
- Review uses the existing bounded 3-5-7 evidence search and one local verdict.
- `SUPPORTED` records the review without changing the claim.
- `INSUFFICIENT_EVIDENCE` preserves the active claim and records the failed
  check.
- A well-supported `CONTRADICTED` verdict quarantines the old claim as disputed.
  It never silently overwrites it or manufactures a replacement.

## Deterministic verification

Run from the project root:

```powershell
python -m unittest discover -s tests -v
```

The real-model contracts remain opt-in:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_query_translation_and_focused_follow_up_contract tests.test_live_ai_contracts.LiveAIContractTests.test_mixed_claim_lifecycle_audit_contract tests.test_live_ai_contracts.LiveAIContractTests.test_curator_entity_hierarchy_and_relation_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```
