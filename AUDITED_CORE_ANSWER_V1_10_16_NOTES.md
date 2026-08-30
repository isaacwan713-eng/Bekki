# Audited Core Answer V1.10.16

Build: `bekki-audited-core-answer-v1-10-16-20260829`

## Outcome

When bounded 3-5-7 research cannot answer a low-impact reusable fact and the
External-AI response contains a complete answer plus questionable adjacent
material, Bekki no longer has to discard the valid core with the rest.

The existing Answer Auditor now returns one of three dispositions:

- `USE_AS_IS`: return the candidate unchanged.
- `USE_CANONICAL_CORE`: return and persist a complete cleaned answer containing
  only facts already asserted by the candidate.
- `REJECT`: use the existing safe stop because the core itself is incomplete,
  conflicting, unsafe, or would require new facts to repair.

The same audited answer is used for the UI and Knowledge provenance. Python
validates only the result shape and routes the AI-selected answer; it does not
classify domains, select facts, correct claims, or add SNH48-specific rules.

## Temporal grounding

The audit packet now includes Bekki's host-local current date with an
authoritative temporal role and repeats that date in the final scope anchor.
The auditor must not substitute its training cutoff or assumed present date.

## Preserved policy

- High-impact questions still require the existing second certification.
- Current people, schedules, scores, prices, and other transient states remain
  current-turn-only.
- Stable and reviewable low-impact knowledge retains its AI-selected lifecycle.
- A cleaned answer is accepted only when deletion alone leaves a complete
  answer; no new AI role, gate, arbiter, external request, or model call was
  added.
