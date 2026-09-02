# Inline Social Video WebView2 Lifecycle Hotfix V1.10.44.1

Build: `bekki-inline-social-video-webview2-lifecycle-hotfix-v1-10-44-1-20260902`

## Fixed

- Detects when a `ResultCard` Python wrapper survives after Qt has deleted its
  underlying C++ widget.
- Never calls `_stop_inline_video()` on an invalid prior card when the user
  starts a different video.
- Clears the global active-player reference when Qt emits the card's
  `destroyed` signal.
- Makes player teardown idempotent: the layout, video host, cover widgets,
  button and WebView2 control are individually validated before cleanup.
- Guards delayed geometry refreshes so a queued callback cannot touch a card
  destroyed during rerendering.

## Preserved behavior

- The first and subsequent YouTube, Shorts and Bilibili cards use the same Edge
  WebView2 backend introduced in V1.10.44.
- Cards remain paused until clicked, only one live card plays at a time, and
  playback stays inside Bekki.
- `停止播放` restores the evidence cover and `打开原帖` remains available.

## Live check

1. Play one Bilibili or YouTube card.
2. Start a different card, including one from a newer Bekki response.
3. Confirm the old player stops, the new card starts, and no
   `Internal C++ object ... already deleted` traceback appears.
