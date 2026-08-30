# Bekki Screenshot Current Evidence V1.10.26

Build ID: `bekki-screenshot-current-evidence-v1-10-26-20260830`

## What this fixes

- Current image evidence remains authoritative through final answer generation.
- An IMAGE or DOCUMENT request cannot be converted into COMPANION merely for warm wording.
- IMAGE replies load zero prior chat turns, so an older screenshot answer cannot replace the current one.
- The current image packet and current user request are appended as the final authoritative prompt section.
- Windows OCR now awaits `IAsyncOperation<T>` with the WinRT awaiter and opens images as `IRandomAccessStream`.
- OCR failures report the exact stage, exception type, and HRESULT in the runtime log.

## Architecture

This release does not add an AI role, model call, or semantic Python classifier.
It reconciles incompatible fields already emitted by Melchior and strengthens
the final evidence boundary.

## Expected screenshot log

For a local screenshot explanation, the important route fields should be:

```text
interaction_mode=TASK
context_profile=IMAGE
needs_balthasar=false
[BALTHASAR SKIPPED] LOCAL_ANSWER
[FINAL PERSONA] LIGHT LOCAL_ANSWER
```

If Windows OCR still cannot start, the log now includes `stage`, `error`, and
`hresult`; the enlarged Gemma tiles continue without OCR.
