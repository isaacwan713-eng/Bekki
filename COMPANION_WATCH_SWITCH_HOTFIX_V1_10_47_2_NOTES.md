# Companion Watch Switch Hotfix V1.10.47.2

Build: `bekki-companion-watch-switch-hotfix-v1-10-47-2-20260902`

## Runtime behavior

- Starting a second inline video first stops the currently active video.
- The old WebView2 control is marked inactive, muted, and sent `Stop()` before
  its event handlers are detached and its widget is disposed.
- A second player is rejected if the first player remains active after cleanup.
- A late initialization callback from an already superseded WebView is muted
  and stopped immediately.
- Moving directly from one theater card to another performs the same full stop.
- Exiting theater without choosing another video still returns the same player
  to its source card without stopping playback.

## Diagnostics

Expected switch diagnostics include both video IDs:

```text
[INLINE VIDEO STOP] platform=bilibili video_id=BV... native_stop=true
[INLINE VIDEO SWITCH] previous=BV... current=BV... stopped=true
```

Audio and theater diagnostics also include `video_id=...`, making late events
from a previous player distinguishable from the current player.
