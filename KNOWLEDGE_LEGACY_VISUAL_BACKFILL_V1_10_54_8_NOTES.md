# Knowledge Legacy Visual Evidence Backfill V1.10.54.8

Build: `bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913`

Parent: Knowledge Visual Recall V1.10.54.7

## What changed

V1.10.54.6 writes visual evidence for newly learned claims and V1.10.54.7
recalls verified local assets. This release adds the missing migration-free path
for older active Knowledge: one normal autonomous cycle may attempt to enrich at
most one image-free verified claim from at most two HTTPS sources already bound
to that exact record.

Backfill never performs a general image search and never changes the existing
claim. A schema-bound Gemma 4 vision matcher receives the fixed claim, current
source text, and at most two images captured from that exact source page. It can
only select exact 1-based image indexes, copy a literal supporting excerpt, and
describe visible support already inside the claim. A separate schema-bound
Gemma 4 vision verifier independently reviews the fingerprinted proposal.

Python accepts an approved proposal only while the claim is still active and
its fingerprint is unchanged. The source ID must remain among the claim's
original public sources. The literal excerpt, image payload, content-addressed
asset ID, SHA-256, MIME signature, byte length, privacy class, media index, and
sealed evidence bundle must all validate before the evidence-only update is
written.

## Safety and scheduling

- Maximum one claim and two already-bound sources per autonomous cycle.
- Only active `verified` stable or unexpired reviewable Knowledge is eligible.
- Claims that already contain image evidence are never backfilled again.
- User uploads, local files, private media, HTTP sources, loopback or private
  network hosts, unbound thumbnails, and broad image search are excluded.
- Logos, avatars, decoration, generic subject pictures, ambiguous identities,
  inferred relationships, and inferred current status must be rejected.
- Claim text, subject, topics, lifecycle, verification status, confidence,
  sources, temporal scope, and curation remain unchanged.
- Evidence-only enrichment does not re-open semantic curation.
- Read errors retry after 7 days, invalid output after 30 days, missing images
  after 90 days, and unsupported/rejected images after 180 days.
- The operational retry ledger stores only claim/source fingerprints and
  bounded status codes. It stores no raw image payload, URL token, or local
  path.
- Installation preserves `data` and performs no eager backfill or Knowledge
  rewrite.

## Validation

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_LEGACY_VISUAL_BACKFILL_V1_10_54_8.ps1
```

The wrapper runs the new backfill tests, then the inherited V1.10.54.7 visual
recall, V1.10.54.6 visual-write, evidence-lineage, and read-only live SQLite
validators.
