# Bekki Stable V1.2

Build: `bekki-stable-v1-2-20260824`

This is a deliberately narrow routing update on top of Stable V1.1. The stable
R25 UI remains byte-for-byte unchanged.

## Fixed in this version

- `我有哪些提醒` is explicitly classified as COMMAND because answering it
  requires reading Bekki's local task store.
- Melchior's first detailed judgment can choose any valid response mode and can
  therefore challenge an incorrect initial MAGI lane.
- A lane disagreement returns to reliable `gemma3:12b` MAGI for an independent
  audit. Only the post-audit Melchior replan is constrained to the audited lane.
- Python validates schemas and lane membership but does not choose a semantic
  lane using keywords.

## Acceptance request

`我有哪些提醒` → MAGI COMMAND → Melchior TASK_ACTION → Casper lists the real
task store, including an empty list when no reminders exist.

Fact lookup accuracy, local file search, recommendations, translation wording,
and UI changes are intentionally outside Stable V1.2.
