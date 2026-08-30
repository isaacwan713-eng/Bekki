# Bekki Screenshot Local Route Contract V1.10.24

Build ID: `bekki-screenshot-local-route-v1-10-24-20260830`

This release fixes the live screenshot explanation failure without adding an
AI role, routing gate, or semantic Python classifier.

- `local_knowledge_sufficiency` now refers only to recalled verified Knowledge,
  never to an attached image, document, or the model's general knowledge.
- A screenshot can fully support `LOCAL` while the Knowledge field is `NONE`.
- When the Knowledge candidate packet is empty, a model-produced `SUFFICIENT`
  or `PARTIAL` auxiliary value is mechanically normalized to `NONE`.
- The valid AI-selected lane is preserved and no recovery model call is spent
  repairing that one impossible auxiliary value.
- Existing screenshot privacy, local Vision extraction, search handoff, and
  ambiguity boundaries are unchanged.
