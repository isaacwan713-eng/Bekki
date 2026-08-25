# Bekki Stable V1

Build: `bekki-stable-v1-20260823`

This release returns to the stable R25 UI and keeps the existing
Melchior → Casper → Balthasar application structure while adding a lightweight
MAGI entry gate and a bounded Ollama runtime.

## Included

- AI-only MAGI classification into exactly one lane: SEARCH, LOCAL, COMMAND.
- One AI recovery judgment for invalid MAGI output; no Python keyword router.
- AI-constrained Melchior recovery when its detailed mode crosses MAGI's lane.
- Cross-thread and cross-process serialization of Ollama work.
- Single-model switching, 12B/4B context caps, request timeout, cleanup, and one
  retry for HTTP 500, connection, timeout, CUDA, and llama-server failures.
- UTF-8 prompt byte budgeting that preserves the rules prefix and current-turn
  suffix instead of allowing oversized evidence packets to break JSON output.
- Recommendation source-card fallback when candidate JSON is incomplete.
- Correct handling of explicit adult-audience recommendation requests.
- Lazy optional Playwright/PySide imports so an unavailable optional component
  does not break unrelated startup/test paths.

## Deliberately unchanged

- `ui.py` and the stable R25 conversation layout.
- Existing user history, memory, tasks, settings, and `.env` during installation.
- Required Ollama models: `llama3.2:latest`, `gemma3:12b`, `gemma3:4b`.

## Acceptance requests

1. `曼联最近有什么新闻？` → MAGI SEARCH → Melchior NEWS_FEED.
2. `我最近工作好累，陪我聊聊` → MAGI LOCAL.
3. `打开回收站` → MAGI COMMAND → Melchior DEVICE_ACTION.
4. Ask for recommendations with long pages: either verified recommendations or
   bounded independent-source cards must remain visible; the result must not
   disappear solely because a model JSON response is incomplete.
5. Stop Ollama during a request: Bekki should report a bounded model failure
   after one retry without closing the desktop application.
