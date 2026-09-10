# Knowledge Visual Recall V1.10.54.7

Build: `bekki-knowledge-visual-recall-v1-10-54-7-20260910`

Parent: Knowledge Autonomous Visual Evidence V1.10.54.6

## What changed

V1.10.54.6 completed the write side of autonomous visual evidence. This release
completes the read side: when MAGI has already judged an active recalled
Knowledge set sufficient for the exact local question, Bekki can attach the
corresponding stored public-source images to the final Gemma answer call.

Visual recall is deterministic and adds no routing, judging, or retrieval model
call. It reads at most two local assets and never follows the stored source URL.
Every asset must still match its claim record, media-index entry, content-addressed
ID, SHA-256 digest, byte length, image signature, extension, public-source
provenance, and `PUBLIC_SOURCE` privacy class. Any mismatch silently downgrades
that answer to the existing text-only Knowledge context.

The final prompt carries an exact 1-based binding between each attached image
and its Knowledge claim. Images remain evidence rather than instructions. They
may help describe visible appearance inside the stored claim's scope, but cannot
establish identity, current status, hidden intent, or a fact absent from the
mandatory text anchor. Embedded commands are explicitly ignored, and the text
claim remains factual authority if visual evidence is ambiguous.

## Isolation and compatibility

- Visual assets are attached only on `LOCAL_ANSWER` when Melchior carries
  `knowledge_route_selected=true`, which originates from MAGI's `SUFFICIENT`
  judgment for the recalled active Knowledge.
- Search, action, routing, Knowledge Judge, Curator, lifecycle, and JSON-format
  recovery calls never receive recalled image bytes.
- Maximum two deduplicated images per final answer call.
- No raw image bytes or local paths enter prompts, Knowledge records, logs, or
  answer history.
- Legacy and text-only Knowledge continue through the unchanged text path.
- Missing, modified, private, malformed, or unsealed assets fail closed without
  a network fallback.
- Root and Casper evidence/retrieval modules are byte-identical.
- Installation preserves the existing `data` directory and performs no
  Knowledge migration or rewrite.

## Validation

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_VISUAL_RECALL_V1_10_54_7.ps1
```

The wrapper runs the new visual-recall tests, then the inherited autonomous
visual-evidence tests and read-only live SQLite validator.
