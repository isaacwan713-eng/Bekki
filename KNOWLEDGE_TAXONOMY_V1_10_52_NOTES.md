# Knowledge Taxonomy V1.10.52

Build: `bekki-knowledge-taxonomy-v1-10-52-20260905`

## What changed

Knowledge now has five independent organization dimensions instead of asking
one field to do several jobs:

- domain: a controlled broad subject area;
- category path: one reusable category and an optional subcategory;
- topic: one coherent entity or knowledge ecosystem;
- fact type: the proposition's stable browse shape;
- L1-L5: learning depth only.

Freshness remains represented only by `knowledge_type`, expiry, temporal scope,
and the existing lifecycle audit. Categories never turn a 2024 fact into a
2022 fact and never make a current fact permanent.

The Topic Lifecycle assessor now classifies unclassified topics and claims in
the same bounded pass used for layering. It reuses established category IDs and
labels when possible. A new path is allowed when the existing catalog does not
fit; a changed classification keeps a bounded audit history. Relationship-
bearing claims must use the `RELATIONSHIP` fact type.

## Storage and compatibility

- Topic JSON schema becomes version 3.
- The SQLite schema remains version 2; no database rebuild is required.
- Existing topic documents are structurally upgraded, then semantically
  classified by the local AI in idle batches of at most six topics.
- Verified claim text, source evidence, entity IDs, relationship edges,
  temporal scope, lifecycle state, and existing L1-L5 assignments are not
  rewritten by the migration.
- `data/knowledge/index.json` now contains `category_paths`, per-topic fact-type
  counts, and global fact-type counts. SQLite remains authoritative and the JSON
  file remains its readable compatibility mirror.

Python validates IDs, completeness, label consistency, and write safety. It
does not decide the semantic category of a topic.

## Browsing API

Use `knowledge.load_category_catalog()` to view the derived category tree and
`knowledge.load_knowledge_by_category(...)` to filter by domain, category,
subcategory, or fact type.

## Scope

This release does not change Bilibili navigation, Bilibili evidence discovery,
inline video playback, or Companion Watch.

## Validation

After Bekki finishes its first idle classification pass, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_TAXONOMY_V1_10_52.ps1
```

The validator is read-only. It checks the SQLite payload hashes, topic schema,
classification contract, category paths, fact types, and preservation of
existing layers, lifecycle states, and relationship metadata.
