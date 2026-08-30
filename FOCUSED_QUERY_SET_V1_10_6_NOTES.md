# Focused Query Set V1.10.6

Build: `bekki-focused-query-set-v1-10-6-20260829`

Baseline: Recycle Action Arbiter V1.10.5

## Fixed behavior

The old shared query-certification contract said that a focused follow-up could
cover one missing facet, but still asked the model to output
`all_facets_preserved`. Gemma 4 sometimes followed the field name instead of
the focused-query instruction, rejected a valid single-facet query, or rewrote
it into a sibling query's facet.

V1.10.6 uses dedicated focused-query AI contracts:

- The focused candidate before audit, the candidate under review, and sibling
  queries have explicit labels.
- The auditor names the current query slot's intended facet.
- Every rewrite must preserve that same focused facet.
- The certifier judges `focused_facet_preserved` for the current query and
  `query_set_collectively_covers_gaps` for the complete effective set.
- The focused schema no longer contains the misleading primary-query field
  `all_facets_preserved`.
- A failed certification gets one dedicated focused repair and one new
  independent certification.
- Python performs structural labeling and schema validation only; semantic
  entity, hierarchy, translation, and facet decisions remain AI-owned.

## Targeted real-model test

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_query_translation_and_focused_follow_up_contract
```
