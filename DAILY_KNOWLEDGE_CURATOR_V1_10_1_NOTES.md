# Daily Knowledge Curator V1.10.1

Build: `bekki-daily-knowledge-curator-v1-10-1-20260828`

## What the real-run log proved

The mixed SNH48 request was correctly governed as current-turn-only overall
with a reusable component. The log did not show a wrong outbound prompt:
`[EXTERNAL AI DESKTOP INPUT] Message ChatGPT` was the accessible name of the
composer control. V1.10.1 renames that diagnostic to
`[EXTERNAL AI DESKTOP INPUT CONTROL]` to remove the ambiguity. The Desktop
adapter sent the governed question but timed out
without a readable answer, so no lifecycle partition or SNH48 inbox record was
allowed.

Separately, the daily curator attempted too many structurally rich assignments
in one response. Gemma reached its output limit before closing valid JSON, and
the equally large recovery response was truncated again. The pending records
were preserved, but that day's organization pass failed.

## Repairs

- Curator batches are capped at three items. Every completed batch is applied
  atomically before the next batch starts, while topic/entity/facet decisions
  remain AI-owned.
- Safe topic and entity ID patterns are included in the structured-output
  schema as well as checked by Python.
- Recovery instructions forbid relabeling distinct claims as duplicates merely
  to shorten output.
- ChatGPT Copy controls are compared by stable UIA runtime identity rather than
  only total count, covering WebView replacement/virtualization.
- Text fallback requires a newly-added exact prompt occurrence. Repeating the
  same question cannot reuse the old prompt anchor.
- Cosmetic zero-width characters and UIA line wrapping are normalized without
  relaxing the semantic prompt match.
- Desktop fallback and timeout logs now expose the exact terminal status and
  the observed anchor/control state.

No SNH48-, member-, sister-group-, or other domain-specific Python classifier
was added.
