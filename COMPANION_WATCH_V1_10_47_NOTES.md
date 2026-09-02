# Companion Watch V1.10.47

Build: `bekki-companion-watch-v1-10-47-20260902`

## Added

- An opt-in `Bekki 陪看` control in Bekki theater mode.
- A collapsible conversation panel rendered inside the lower-right of the
  verified YouTube/Bilibili player surface.
- User input and Bekki replies that remain isolated from the main chat history.
- Low-frequency frame reactions through the lightweight `gemma4:e4b` model.

## Runtime boundaries

- V1 reads the visible video frame and verified card title only; it does not
  capture a microphone, system audio, subtitles from another API, or browser
  credentials.
- Static/paused frames are rejected by a small perceptual-change gate before
  a model call.
- Only one companion model request may run at a time. Normal user turns and
  NERV maintenance retain priority.
- A session generation and exact video URL bind every result. Exiting theater,
  stopping playback, or switching video invalidates late replies.
- Web content and text in the captured frame are treated as untrusted data.

## UI and navigation safety

- The panel uses WebView2's local wrapper message bridge because native
  WebView2 surfaces cover ordinary Qt child overlays.
- Displayed text is inserted with `textContent`, input is capped at 320
  characters, and the wrapper cannot open a new page, popup, or download.
- Companion Watch is disabled by default and closes with theater mode.
