# NERV Curiosity Soft Gate V1.7

Build: `bekki-nerv-curiosity-soft-gate-v1-7-20260827`

## Decision boundary

- Writer `interest_score` and `confidence` are uncalibrated model hints, not
  probabilities and not normal hard rejection thresholds.
- Safe, well-formed, language-matched candidates proceed to the independent
  Curiosity Selector even when their scores are moderate.
- Only an extremely low writer confidence below `0.40` is rejected before
  selection.
- Privacy, malformed contract, outbound language, and exact duplicate gates
  remain deterministic.

## Observability

- `[NERV CURIOSITY OBSERVED]` now prints the exact rejection reason.
- The audit journal records all triggered rejection reasons plus both scores.
- Selector packets include both `interest_score` and `confidence` as soft
  context.

## Regression

- The observed SNH48 candidate with `interest_score=0.7` and
  `confidence=0.8` must be drafted rather than dismissed.
- Extremely low confidence, sensitive sharing, and language mismatch remain
  rejected.
- Curiosity, External AI Desktop, runtime, NERV, routing, screenshot-search,
  and UI regression suites: `147/147` passed.
