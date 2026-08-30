# Bekki Screenshot Multipass OCR V1.10.27

Build ID: `bekki-screenshot-multipass-ocr-v1-10-27-20260830`

## Changes

- Panoramic screenshots receive full, enlarged-left, and enlarged-right local OCR passes.
- All passes share the existing 15-second OCR budget and fail open to Gemma Vision.
- The existing Gemma Vision call compares pass disagreements against its pixel tiles.
- Literal OCR observations survive into the authoritative current-image final context.
- `visible_text` grows from 12 to 24 entries so lower UI rows are retained.
- Bare numbers cannot be labeled views/comments/reposts/likes without visible structural support.
- Text marked garbled or disputed cannot be quoted as exact in the final answer.

This release adds no AI model, semantic Python classifier, or routing gate.

## Expected log

For a wide screenshot with working Windows OCR:

```text
[VISION WINDOWS OCR] status=COMPLETED ... passes=3 ...
```

The final route should remain `TASK + IMAGE` with Balthasar skipped.
