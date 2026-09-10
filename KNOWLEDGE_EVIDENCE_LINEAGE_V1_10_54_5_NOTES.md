# Knowledge Evidence Lineage V1.10.54.5

Build: `bekki-knowledge-evidence-lineage-v1-10-54-5-20260909`

This release adds a source-evidence layer to Bekki's unified SQLite-backed
Knowledge system. Newly extracted public-source claims carry this evidence;
policy-only and legacy claims remain explicitly distinguishable. It does not
change the SQLite schema version: evidence
bundles and the media index are versioned JSON documents stored through the
existing schema-v2 document contract.

## Evidence contract

- New autonomous source claims require a literal excerpt from the opened page.
- The Knowledge Judge is bound to the exact evidence fingerprint as well as
  the existing candidate fingerprint.
- Accepted fact lookups and verified Curiosity results retain the evidence
  records selected during extraction.
- Every record, claim bundle, source snapshot, and media asset has a SHA-256
  integrity anchor.
- Earlier evidence is merged rather than silently replaced when a claim is
  updated or reverified.

## Public image information

- The single-source extractor reports `TEXT`, `IMAGE`, `TEXT_AND_IMAGE`, or
  `NONE`, plus exact text and selected source-image indexes.
- Only PNG, JPEG, and WebP bytes from a public HTTP(S) source are eligible.
- A selected image is stored once by content hash under
  `data/knowledge/media/assets`.
- `data/knowledge/media/index.json` is an SQLite-authoritative compatibility
  mirror containing source, MIME type, size, hash, and relative path metadata.
- Claims retain the bounded visual observation and asset IDs, so image meaning
  is searchable without putting base64 image bytes into normal prompts.
- User uploads, local files, private media, and unbound thumbnails are rejected
  by the automatic persistence boundary.

## Compatibility and inspection

- Existing Knowledge claims remain valid without evidence bundles and keep
  their previous curation fingerprints; no bulk rewrite or recuration occurs.
- `knowledge.load_knowledge_evidence(knowledge_id)` returns a safe evidence
  view. Pass `include_asset_paths=True` only for local inspection.
- `knowledge.audit_knowledge_evidence()` validates bundles and public-media
  files without changing claim semantics.
- Topic curation and retrieval receive bounded text/visual summaries, never raw
  image payloads.

## Unchanged boundaries

Bilibili playback, logged-in playback quality, Companion Watch, UI, and font
behavior are unchanged. The release only reuses already captured, explicitly
selected public-source frames after factual acceptance.
