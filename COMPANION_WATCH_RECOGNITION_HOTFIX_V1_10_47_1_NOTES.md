# Companion Watch Recognition Hotfix V1.10.47.1

Build: `bekki-companion-watch-recognition-hotfix-v1-10-47-1-20260902`

## Fixed

- User questions no longer restart the proactive-reaction timer. The initial
  observation remains due about eight seconds after companion mode starts.
- Direct visual questions use `gemma4:12b`, a frame up to 1280×720, and JPEG
  quality 84. Automatic reactions continue using `gemma4:e4b` at 960×540.
- Direct answers must inspect concrete visible cues, honor corrections, and
  avoid returning the observation task to the user as a question.
- The first usable automatic frame must produce a reaction. Blank/loading
  frames remain silent and failed first looks may retry.
- Wrapper messages are sent as JSON strings to avoid qtwebview2's misleading
  `Received invalid message from JS bridge` diagnostic.

## Diagnostics

Each submitted frame logs its request kind, dimensions, and encoded size:

`[COMPANION WATCH FRAME] kind=USER_MESSAGE size=1280x720 jpeg_kb=...`

Direct-answer models unload after the response (`keep_alive=0s`) so a 12b
inspection does not remain resident beside video playback.
