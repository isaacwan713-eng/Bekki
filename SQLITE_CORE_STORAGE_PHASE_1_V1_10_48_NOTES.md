# SQLite Core Storage Phase 1 V1.10.48

Build ID: `bekki-sqlite-core-storage-phase-1-v1-10-48-20260902`

Baseline: Balthasar Companion + Social JSON Hotfix V1.10.47.8.

## Phase-one boundary

This release migrates the core state needed to resume a conversation safely:

- `data/chat_history.json`
- `data/contexts/<session>.json` and legacy `data/context.json`
- `data/tasks.json`
- `data/temporary.json`
- `data/task.json` (legacy memory task document)
- `data/profile.json` (legacy long-term memory document)
- `data/pending.json`

Knowledge, NERV governance, learned skills and audit JSON/JSONL remain outside
this phase. Emotion, UI preferences, location and localization caches also stay
on their existing storage paths.

## Storage contract

- The single phase-one database is `data/bekki.sqlite3`.
- Existing readable JSON is imported automatically and idempotently on first
  access; no manual conversion command is required.
- Each original JSON generation is copied once to
  `<file>.pre-sqlite-v1.bak` before its first import.
- SQLite is authoritative after migration. The old JSON path remains an atomic
  mirror so V1.10.47.8 can still read state after a code rollback.
- If a rolled-back build later changes a JSON mirror, V1.10.48 recognizes the
  newer filesystem generation and imports it back into SQLite.
- A missing or malformed mirror is rebuilt from the committed SQLite value.
- If SQLite is unavailable, reads and writes fail open to the JSON path so the
  desktop assistant remains usable.

## Durability and concurrency

The shared storage layer enables WAL journaling, `synchronous=FULL`, foreign
keys, a ten-second busy timeout, atomic JSON replacement, last-known-good JSON
backups and both thread-level and process-level serialization. The process lock
covers the SQLite commit plus compatibility mirror, preventing two Bekki
workers from leaving those generations out of order.

## Validation

Dedicated tests cover:

- exact migration backup preservation and idempotency;
- corrupt and missing mirror recovery;
- rollback-version JSON re-import;
- SQLite-newer crash recovery;
- concurrent writer consistency;
- unavailable-database fallback;
- shared-database integration across memory, history, tasks and context;
- removal of deleted session context from both SQLite and JSON.
