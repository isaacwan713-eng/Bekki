# Topic Lifecycle Isolation V1.10.54.4

Build: `bekki-topic-lifecycle-isolation-v1-10-54-4-20260909`

Parent: Knowledge Curator Terminal Outcomes Hotfix V1.10.54.3.1

## Why this release exists

The Curator already isolated one verified Knowledge item at a time, but its
immediate Topic Lifecycle pass only *preferred* the touched Topic. It could
still assess or open Curiosity for an unrelated Topic. Lifecycle model output
also was not cryptographically bound to the Topic evidence snapshot that
produced it, and a malformed first response was copied into recovery context.

## Isolation contract

- Each lifecycle request contains exactly one compact Topic evidence packet.
- The JSON Schema binds the exact Topic ID, exact pending Knowledge IDs, the
  lifecycle assessment contract version, and a SHA-256 evidence fingerprint.
- The same fingerprint is checked again under the Knowledge write lock. If the
  Topic changed while the model was running, the result is rejected before any
  Topic or flat-ledger write.
- The one recovery attempt receives a fresh bounded packet plus error codes;
  the invalid first model response is deliberately absent.
- Optional category and Curiosity context is bounded to 12,000 UTF-8 bytes.
  Claim IDs and pending-ID evidence are never dropped to make a packet fit.

## Topic-local scheduling

When the Curator commits one or more items, its immediate lifecycle pass is
restricted to the exact touched Topic IDs. It cannot assess, refresh, or seed
Curiosity for another Topic in that pass. The independent idle lifecycle pass
continues to consider all eligible Topics.

Due refresh work ranks ahead of ordinary open gaps; `interest_score` ranks
within the same urgency class. One invalid Topic does not block later Topics,
and a mixed run reports `COMPLETED_WITH_ERRORS` with per-Topic diagnostics.

## Compatibility and storage

Existing Topic lifecycle rows remain valid as legacy-compatible records. They
are upgraded to assessment contract version 1 only when a normal future
assessment is already due. Installation does not rewrite SQLite facts,
relationships, classifications, history, or Curiosity entries.

The live validator opens SQLite in read-only mode and uses the same generic
Topic audit for every subject. There are no AKB48-, Manchester United-, or
四禧丸子-specific production rules.

## Unchanged behavior

Bilibili search and playback, fixed-site routing, the UI and font work,
Companion Watch, and the user's existing data directory are unchanged.

## Validation

After installation and with Bekki closed, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_TOPIC_LIFECYCLE_ISOLATION_V1_10_54_4.ps1
```

Legacy rows may appear under `legacy_compatible`; this is expected. The test
passes when the generic lifecycle audit, mirrors, payload hashes, build wiring,
and Companion Watch guard are all valid.
