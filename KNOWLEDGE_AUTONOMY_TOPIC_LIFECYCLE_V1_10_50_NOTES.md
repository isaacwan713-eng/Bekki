# Knowledge Autonomy + Topic Lifecycle V1.10.50

Build ID: `bekki-knowledge-autonomy-topic-lifecycle-v1-10-50-20260903`

This release completes Bekki's autonomous Knowledge-to-Curiosity loop on top
of SQLite Knowledge + NERV Storage Phase 2 V1.10.49.

## Behavior

- Verified knowledge first passes through the existing AI curator and receives
  an exact topic identity before it can trigger another question.
- A separate AI topic assessor assigns every verified claim to L1 Foundation,
  L2 Context, L3 Relationships, L4 Mechanisms, or L5 Specialist.
- The assessor defines the current target layer, marks all five coverage
  states, records an interest score, and chooses `ACTIVE` or
  `PAUSED_COMPLETE`.
- Python enforces the transition contract: an incomplete batch, missing
  required layer, low completion score, absent reason, or invalid refresh
  interval cannot be committed as complete.
- `ACTIVE` topics may generate one evidence-bound gap question. Completed
  topics remain quiet until their AI-selected refresh date, a reviewable fact
  approaches expiry, or the user explicitly re-engages with the topic.
- When several topics are eligible, only the highest-interest one is selected.
  One unresolved lifecycle question blocks additional autonomous questions,
  and failed/declined/drafted attempts are throttled.
- The GUI idle curator and Windows scheduled Knowledge worker use the same
  lifecycle manager, so successful learning runs organize and assess their new
  knowledge without waiting for a later GUI session.

## Storage and rollback

No database schema migration is introduced. Knowledge topic documents,
Curiosity state and their audit events continue through the Phase 2 SQLite
authority with readable JSON/JSONL compatibility mirrors. Existing
`.pre-sqlite-v1.bak` and `.pre-sqlite-v2.bak` migration snapshots are not
rewritten. The installer continues to preserve the entire installed `data`
directory and restores the previous runtime if validation fails.

## Safety validation

Automated tests cover exact topic binding, L1-L5 batch completion, invalid
pause rejection, same-pass curation and assessment, single-question locking,
highest-interest selection, due refresh, seven-day reviewable expiry wake-up,
user re-engagement, SQLite schema-2 persistence, JSON/JSONL fallback, and the
complete legacy regression suite.

After Bekki has started once, run
`TEST_KNOWLEDGE_AUTONOMY_V1_10_50.ps1` for a read-only SQLite and lifecycle
status report. It does not create, edit, layer, pause, or refresh any topic.
