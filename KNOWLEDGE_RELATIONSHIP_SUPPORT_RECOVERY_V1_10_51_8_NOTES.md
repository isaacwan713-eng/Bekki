# Knowledge Relationship Support Recovery V1.10.51.8

Build ID: `bekki-knowledge-relationship-support-recovery-v1-10-51-8-20260904`

## Live failure reproduced

The V1.10.51.7 live validator found a real migration edge case in the
`sihixian_ecosystem` topic. The current roster claim remained `verified`, was
reviewable through 2027-09-04, and still retained all four exact curator
relationship IDs in the authoritative flat ledger. The topic edge, however,
kept only the closed 2022 support and projected as `HISTORICAL_ONLY`.

The edge had two valid support claims with different evidence clauses. During
the contract-v2 rebuild, the legacy edge-level `claim_relation_evidence` held
the last historical clause. V1.10.51.7 incorrectly required that one clause to
match every support, so the current claim was removed even though its own
per-claim evidence and curator relationship metadata were valid.

## Recovery behavior

- Each support is grounded against its own `evidence[]` text before the
  ambiguous edge-level compatibility field is considered.
- A database already touched by V1.10.51.7 can restore missing support only
  from the authoritative flat ledger when claim ID and complete claim text
  match exactly.
- Restored curator relationship IDs must match the existing raw or canonical
  semantic relationship ID.
- Endpoint names must still occur in the verified claim evidence. The recovery
  cannot create a new relationship from an unrelated same-ID topic copy.
- Existing relationship IDs, claim IDs, current/historical views, lifecycle
  rules, SQLite schema version 2, and immutable migration snapshots remain
  unchanged.

## Windows validator correction

Windows PowerShell 5.1 may re-encode a here-string while piping it to
`python -`. The earlier live script embedded Chinese comparison literals, so
the database could print correct Chinese names while the comparison constant
was decoded differently. V1.10.51.8 uses Python Unicode escape constants for
the four-member assertion, removing this false-negative path.

## Validation

Run with Bekki and Knowledge Scheduler closed:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_RELATIONSHIP_SUPPORT_RECOVERY_V1_10_51_8.ps1
```

The live section must report an empty `projection_failures`, contract version
2, support migration version 1, four current edges, four historical edges for
the recovered topic, and `CURRENT_AND_HISTORICAL` status while both claims are
active.

UI, font rendering, browser routing, inline playback, audio, WebView2, and
Companion Watch are byte-identical to V1.10.51.7.
