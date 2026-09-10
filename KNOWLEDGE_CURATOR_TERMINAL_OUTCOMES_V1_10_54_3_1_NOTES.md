# Knowledge Curator Terminal Outcomes Hotfix V1.10.54.3.1

Build: `bekki-knowledge-curator-terminal-outcomes-hotfix-v1-10-54-3-1-20260908`

Parent: Knowledge Curator Isolation V1.10.54.3

## Live finding

V1.10.54.3 successfully processed the four verified AKB48 items one at a time:
all four model decisions were `PRIMARY_VALID`, no item failed, three were
curated into `akb48_ecosystem`, and one team-structure statement was recorded
as a conflict with an existing structural claim. The inbox was empty and no
AKB48/四禧丸子 cross-topic claim existed.

The release validator nevertheless failed because it required every known
AKB48 ID to have `curation.status=curated`. That requirement was too narrow:
`DUPLICATE` and `CONFLICT` are deliberate, safe Curator terminal outcomes.

## Generic terminal-outcome contract

This hotfix removes all hard-coded AKB48 Knowledge IDs from the live rule and
audits every terminal Curator outcome in the SQLite Knowledge store:

- `CURATED` resolves to an existing Topic, the exact authoritative claim
  snapshot, and an existing subject entity in that Topic.
- `DUPLICATE` resolves to a distinct existing claim contained in a real Topic.
- `CONFLICT` resolves to its exact conflict record. That record must own the
  current Knowledge ID, preserve its subject and claim, name a real Topic, and
  reference one or more distinct existing claims in that same Topic.
- Terminal curation-inbox rows must agree with the authoritative flat ledger.
- Missing targets, self-targets, mismatched Topics, corrupted snapshots, and
  broken conflict records fail closed.

New terminal outcomes also store their contract version and extra Topic/target
trace metadata. Existing V1.10.54.3 conflicts remain valid because their Topic
and related claims are recovered from the authoritative conflict record; no
SQLite migration or rewrite is needed.

AKB48 remains in unit tests only as the regression fixture for the original
cross-topic model-memory bug. Production validation contains no AKB48-specific
topic, subject, or Knowledge ID rule.

## Unchanged behavior

Curator single-item isolation, source discovery, Knowledge Judge policy,
Curiosity, Topic lifecycle, Bilibili search and playback, the UI, and Companion
Watch are unchanged.

## Validation

After installation, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_CURATOR_TERMINAL_OUTCOMES_V1_10_54_3_1.ps1
```

The prior live database should now report one valid conflict and
`terminal_outcome_failures = []` without rerunning the Knowledge scheduler.

