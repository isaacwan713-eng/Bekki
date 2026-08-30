# Query Certifier Calibration V1.10.7

Build: `bekki-query-certifier-calibration-v1-10-7-20260829`

Baseline: Focused Query Set V1.10.6

## Root cause

The adversarial PRIMARY query certifier conflated two different standards:

- whether a literal query clearly communicates the intended entity scope;
- whether a search engine can guarantee that no adjacent result will appear.

The second standard is impossible. It caused the certifier to reject even an
explicit qualifier such as `Shanghai group only`. Its prompt also ended with a
prefilled `accepted:false` JSON object, which anchored Gemma 4 toward rejection.

## Correction

- The existing auditor and certifier are retained; no third AI gate was added.
- Normal success still uses two model calls. Failure still permits only the
  existing audit/certification retry, for a maximum of four calls.
- The certifier now judges whether the query itself could be read as requesting
  an adjacent scope. Merely receiving an irrelevant result does not count.
- Explicit entity-only or adjacent-scope exclusion wording is sufficient when
  it semantically communicates the hierarchy boundary.
- Parenthetical literal qualifiers remain part of the query.
- Translation accuracy is judged independently from hierarchy.
- Prefilled rejection/rewriting examples were removed from PRIMARY prompts;
  the supplied JSON schema still enforces output structure.
- A deterministic architecture test prevents adding a third query-scope
  arbiter later.

## Targeted real-model test

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_query_translation_and_focused_follow_up_contract
```
