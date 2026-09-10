# Knowledge Autonomous Visual Evidence V1.10.54.6

Build: `bekki-knowledge-autonomous-visual-evidence-v1-10-54-6-20260909`

Parent: Knowledge Evidence Index Bootstrap Hotfix V1.10.54.5.1

## What changed

The approved-source background worker no longer discards all webpage imagery.
When autonomous learning opens a public source, the reader can now collect at
most two meaningful public HTTPS images from that exact page. Static HTML uses
source-carried image URLs; the browser fallback can capture bounded rendered
image elements on JavaScript-backed pages.

The image path rejects tiny, blank, duplicate, decorative, non-HTTPS, unsafe,
oversized, and unsupported candidates. Query strings and credentials are never
written to the media index. User uploads, local files, private media, search
thumbnails, and images that are not carried by the opened source remain outside
this automatic path.

`knowledge_extract.txt` is now a schema-bound multimodal extraction contract.
The extractor must select the exact 1-based image indexes and produce a bounded
visible observation. A literal source-text excerpt remains mandatory for every
candidate: visual evidence may supplement a text-anchored claim but cannot
create an image-only reusable fact.

The selected image bytes participate in the candidate evidence fingerprint.
The Knowledge Judge sees the fingerprint and compact evidence metadata, never
the raw base64 payload. After a normal accepted or pending persistence outcome,
the evidence layer normalizes and content-addresses the public image, stores its
portable metadata in SQLite, and leaves only asset IDs in the Knowledge claim.

Learning logs now include `visual_evidence` accounting for captured images,
image-backed candidates, and claims with persisted image assets. Installation
does not rewrite existing Knowledge or synthesize missing evidence.

## Safety and compatibility

- Maximum two images per opened source and per claim.
- Existing text-only extraction responses remain valid and produce text-only
  evidence.
- Invalid image indexes or payloads downgrade to literal text evidence.
- Root and Casper runtime copies are byte-identical.
- The inherited read-only evidence validator remains pre-start safe for legacy
  stores without an initialized media index.
- Playback, Companion Watch, UI, fonts, and existing scheduled-task semantics
  are unchanged.

## Validation

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_AUTONOMOUS_VISUAL_EVIDENCE_V1_10_54_6.ps1
```

The wrapper runs the new autonomous visual-evidence tests and the inherited
Knowledge Evidence Lineage live SQLite validator.
