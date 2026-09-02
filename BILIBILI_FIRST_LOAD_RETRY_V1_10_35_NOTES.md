# Bilibili First-Load Retry V1.10.35

## Observed failure

Bilibili's first search navigation could display an empty result area. A
manual refresh of that same tab then displayed the real results, but Bekki had
already sampled the empty first load and completed the task with zero cards.

## Recovery contract

- Bekki checks native response candidates and rendered cards before capture.
- If both are empty, it refreshes the same Bilibili tab exactly once.
- The native response listener is attached on the active inspection connection
  before that refresh.
- Only post-refresh text, screenshots, and candidates are sampled.
- A successful first load is never refreshed.
- A second empty load remains fail-closed; there is no refresh loop.
- New unified Edge launches suppress the browser translation prompt.

The recovery uses the existing unified Edge session on port 9225 and adds no
search provider, model call, AI role, or arbitration gate.
