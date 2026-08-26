# Bekki External AI + NERV Curiosity V1

Build ID: `bekki-external-ai-curiosity-v1-20260825`

This update keeps the NERV Learning V1.3 runtime and adds a separate,
observable External AI layer. It does not use an OpenAI API.

## Explicit External AI

- Example: `帮我问 ChatGPT：为什么猫会呼噜？`
- Bekki opens a dedicated visible Edge profile and sends only the governed,
  self-contained question.
- Login and browser security verification remain human-only. Complete them in
  the visible window, then return to Bekki and reply `继续`.
- Bekki shows the exact prompt and labels the ChatGPT answer as external and
  unverified. It is not automatically written into Knowledge.

## Curiosity Journal

- NERV may draft a useful question after a completed turn.
- A reliable local AI applies privacy and quality gates, and a second focused
  AI selects one exact due draft at a time, up to the configured daily limit
  (three by default).
- Bekki asks it through the same dedicated visible ChatGPT browser.
- States are `DRAFT`, `ANSWERED_UNVERIFIED`, `VERIFIED`, and `DISMISSED`.
- Ask `你今天在想什么？` or `你最近问了 ChatGPT 什么？` to read the
  journal.

The system never claims consciousness. Curiosity is an AI-generated,
user-observable research journal. Sensitive or private context is not sent in
V1, and failed login attempts do not repeatedly reopen the browser that day.
