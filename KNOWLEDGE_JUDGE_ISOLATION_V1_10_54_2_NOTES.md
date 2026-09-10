# Knowledge Judge Isolation V1.10.54.2

Build ID: `bekki-knowledge-judge-isolation-v1-10-54-2-20260908`

Parent: Knowledge Source Recovery V1.10.54.1

## Live failure fixed

The first V1.10.54.1 AKB48 run successfully approved Wikipedia and extracted
four relevant candidates, but `judge_knowledge` serialized the most recent 80
complete Knowledge records. The input reached about 150 KB, was compacted by
the model runtime, and Gemma answered with unrelated 四禧丸子 prose instead of
the required JSON. All four candidates therefore remained pending and the run
correctly ended as `NO_VERIFIED_EVIDENCE`.

## Candidate-anchored Judge contract

- The Judge sees only bounded source metadata, the current candidate, and at
  most twelve compact same-subject or same-topic comparison records.
- Large provenance, revision, evidence, and unrelated Topic fields never enter
  the request.
- Python derives a deterministic candidate fingerprint. The JSON Schema
  requires the model to echo that exact fingerprint.
- Invalid JSON, an incorrect fingerprint, or an invalid target gets one retry
  with no existing-history records and a dedicated compact recovery prompt.
- A second invalid result fails closed as `PENDING_REVIEW` and carries
  `_judge_output_status=INVALID_JSON` for the learning log.

## Pending identity and promotion

- Exact deterministic Knowledge IDs cannot be appended repeatedly while the
  Judge is unavailable.
- A valid later AUTO_SAVE promotes the exact pending row in place.
- A valid UPDATE can target the pending row explicitly.
- Exact already-verified AUTO_SAVE output is treated as a structural duplicate.
- Invalid output cannot verify, update, reject, deduplicate, or downgrade an
  existing verified row.

## Source ranking and diagnostics

- Wikipedia is an established reference and ranks before Fandom, Namu Wiki,
  Grokipedia, Generasia, and generic community-wiki domains.
- Learning logs add extracted-candidate and Knowledge Judge counters.
- A no-evidence result now distinguishes missing approved sources, readable
  sources with no extracted candidates, semantic pending review, and invalid
  candidate-anchored Judge JSON.

## Compatibility and safety

- SQLite schema version remains 2 and existing history is not rewritten.
- Source Discovery contract remains 2 and Source Recovery contract remains 1.
- Knowledge Judge contract is 2; Judge Isolation and Pending Identity contracts
  are 1.
- Bilibili search/navigation, inline playback, UI, and Companion Watch are
  unchanged.

Run the Windows validator after installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_JUDGE_ISOLATION_V1_10_54_2.ps1
```
