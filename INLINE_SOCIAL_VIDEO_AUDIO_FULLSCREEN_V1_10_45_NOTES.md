# Inline Social Video Audio + Bekki Fullscreen V1.10.45

Build: `bekki-inline-social-video-audio-fullscreen-v1-10-45-20260902`

## Bilibili audio

- Keeps every social-video card static and paused until the user clicks
  `在 Bekki 播放`.
- Sends Bilibili's documented `muted=0` external-player parameter.
- Clears `CoreWebView2.IsMuted` during initialization and twice after the
  embedded player document loads.
- Observes WebView2 mute and document-audio changes while the card is active.
- Emits bounded diagnostics such as:
  `[INLINE VIDEO AUDIO] platform=bilibili reason=player_loaded muted=false playing=true`.
- Detaches the added WebView2 audio events during the existing idempotent stop
  path, so switching cards retains the V1.10.44.1 lifecycle fix.

## Bekki fullscreen

- Adds a fullscreen button to Bekki's header.
- F11 toggles the entire Bekki workspace.
- Esc exits fullscreen only when Bekki is currently fullscreen.
- Restores the previous normal geometry or maximized state when leaving.
- Keeps history/task drawer toggles responsive without forcing a fullscreen or
  maximized window back to a narrow fixed width.

## Verification focus

1. Click a Bilibili card's Bekki play button and confirm audible output.
2. Confirm the log reports `muted=false`; once media starts it should report
   `playing=true`.
3. Switch between Bilibili and YouTube cards and confirm the previous player
   stops without a `libshiboken` traceback.
4. Enter fullscreen from the header and F11, then leave with Esc and confirm
   the prior window size/state is restored.

