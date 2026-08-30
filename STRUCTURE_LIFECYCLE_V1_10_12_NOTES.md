# Structure Lifecycle Authority V1.10.12

Build: `bekki-structure-lifecycle-v1-10-12-20260829`

## Corrected lifecycle boundary

- A complete official set of formal departments, teams, branches, provisions,
  standards, or other canonical units is a maintained set or structure.
- The words `currently` and `as of` do not by themselves make that set
  current-turn-only.
- A roster is the people assigned to those units. Current people, individual
  affiliations, lineups, schedules, prices, and events remain transient.
- This distinction is expressed generically in the existing AI contracts; no
  SNH48, team-name, language, or domain keyword rule was added to Python.

## One final lifecycle AI

- The existing partitioner still separates the external answer into atomic
  claims and proposes initial lifecycles.
- The existing lifecycle auditor is the final semantic judge. It may correct
  the partitioner's `persist` proposal in either direction without a new model
  role or call.
- Python checks only non-semantic eligibility: low impact, directly supported
  by the answer, no known evidence conflict, confidence at least 0.80, and
  nonempty atomic claim fields.
- An ineligible claim cannot be persisted even if the model requests it; the
  workflow retries once for structural recovery and otherwise fails closed.
- Lifecycle audit V7 makes older mixed claims eligible for idle re-audit while
  preserving their exact claim text.

## SNH48 acceptance contract

For the mixed SNH48 test, the formal Team set must persist as stable or
reviewable with `MAINTAINED_SET_OR_STRUCTURE`; the definition of `期生` may
persist as durable knowledge; a named person's current membership must remain
changing with `persist:false`.

Run the focused real-model contract after installation:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_formal_unit_set_survives_mixed_answer_partition_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```
