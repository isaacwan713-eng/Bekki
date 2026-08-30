# Focused Certifier Calibration V1.10.8

Build: `bekki-focused-certifier-calibration-v1-10-8-20260829`

Baseline: Query Certifier Calibration V1.10.7

## Observed failure

The PRIMARY query passed after V1.10.7, but the dedicated focused certifier
still rejected a literal query equivalent to “official members classified by
joining batch (期生).” It demanded explicit wording that excluded trainees and
the wider brand ecosystem even though the positive taxonomy and exact entity
already defined the intended search.

## Correction

- No new AI role, gate, arbiter, or model call was added.
- The existing focused auditor and certifier retain their original retry
  budget.
- An exact named entity is not broadened merely because related brands exist.
- A precise joining cohort/batch description plus the source-language taxonomy
  can distinguish trainee status without an explicit negative exclusion.
- The possibility of irrelevant results is not treated as ambiguity in the
  query itself.
- Translation checks are independent from entity hierarchy checks.
- Prefilled `accepted:false` and forced rewrite examples were removed from all
  focused prompts; JSON schemas still enforce the output contracts.
- Existing architecture tests continue to prohibit a third query arbiter.

## Targeted real-model test

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_query_translation_and_focused_follow_up_contract
```
