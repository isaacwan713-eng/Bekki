# Knowledge Evidence Index Bootstrap Hotfix V1.10.54.5.1

Build: `bekki-knowledge-evidence-index-bootstrap-hotfix-v1-10-54-5-1-20260909`

## Live failure reproduced

Running the V1.10.54.5 PowerShell validator before the first upgraded Bekki
startup left `knowledge/media/index.json` absent from the live SQLite store.
The ledger was healthy: all 24 existing claims were correctly classified as
`legacy_compatible`, contract accounting was valid, and no evidence or payload
hash failures were present. The validator nevertheless treated the not-yet-
initialized empty media index as corruption.

The AKB48 source, Knowledge Judge, Curator, and lifecycle messages printed
above that final audit were isolated unit-test fixtures; they were not a live
autonomous-learning cycle.

## Hotfix behavior

- A pre-start store with only legacy or text-only claims may validate before
  the empty media-index document has been initialized.
- Any image claim, referenced media asset, or stored media asset still requires
  the authoritative SQLite media index.
- Malformed media accounting fails closed and still requires the index.
- The validator remains fully read-only (`mode=ro` plus
  `PRAGMA query_only=ON`).
- The first real Bekki/Knowledge initialization still creates the empty index
  through the existing SQLite document contract.

## Safety boundary

No legacy claim is rewritten or given invented source evidence. Existing
knowledge, topic lifecycle state, Curator state, Companion Watch, UI, and media
playback behavior are unchanged. New public-source text and image evidence
continues to use the V1.10.54.5 hash-bound lineage contract.
