# SQLite Knowledge + NERV Storage Phase 2 V1.10.49

Build ID: `bekki-sqlite-knowledge-nerv-phase-2-v1-10-49-20260903`

This phase upgrades `data/bekki.sqlite3` from schema 1 to schema 2 without
rewriting or deleting any Phase 1 document. It adds:

- nested SQLite JSON documents for the knowledge corpus, sources, learning
  logs, clusters, curation state, topic index/conflicts and topic documents;
- nested SQLite JSON documents for the NERV profile, curiosity journal and
  NERV learned-skill compatibility view;
- ordered SQLite event streams for NERV profile audit, curiosity audit and
  learning events;
- immutable `.pre-sqlite-v2.bak` source snapshots plus readable JSON/JSONL
  rollback mirrors;
- recovery of missing/corrupt mirrors and no-loss merging of event appends
  made by a rolled-back build;
- thread/process serialization, WAL, full synchronous commits and JSON/JSONL
  fallback when SQLite is unavailable.

Not migrated in this phase: Casper's executable skill registry and skill-run
log, application skills, emotion, UI preferences, location/localization, and
verified-video site settings.

## Safety validation

Automated coverage includes schema-v1 in-place upgrade, exact snapshot
preservation, malformed JSONL recovery, rollback append merging, missing-mirror
reconstruction, unavailable-database fallback, multiprocess append integrity,
knowledge topic persistence, NERV constructor safety, and the complete legacy
test suite.

For a live installation, close Bekki and its knowledge scheduler, run
`INSTALL_STABLE_V1.bat`, then start Bekki once. Keep both `.pre-sqlite-v1.bak`
and `.pre-sqlite-v2.bak` files; the installer itself continues to preserve the
entire `data` directory and makes a timestamped runtime backup.
