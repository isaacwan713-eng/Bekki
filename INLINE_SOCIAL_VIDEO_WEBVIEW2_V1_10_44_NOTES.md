# Inline Social Video WebView2 V1.10.44

Build: `bekki-inline-social-video-webview2-v1-10-44-20260902`

## Changed

- Replaces QtWebEngine with a single Edge WebView2 backend for YouTube,
  YouTube Shorts and Bilibili result cards.
- Serves each verified iframe from a bounded virtual HTTPS origin inside Bekki,
  giving YouTube the parent identity required to avoid player error 153.
- Uses the installed Edge media stack, including normal H.264 support, instead
  of the codec-limited QtWebEngine build that rejected Bilibili playback.
- Pins `qtwebview2==0.5.0`; the PowerShell installer installs it into Bekki's
  active virtual environment when absent.
- Keeps a dedicated player profile under `data/webview2_video_profile`, ready
  for a later shared playback-state and Bekki co-watching layer.

## Preserved behavior

- Every video is a paused static evidence card until the user clicks
  `在 Bekki 播放`.
- Starting another video closes the previous WebView2 control; `停止播放`
  disposes the player and restores the original cover or evidence frame.
- Playback stays inside the card. Top-level navigation, popups and downloads
  are blocked, while `打开原帖` remains an explicit separate action.
- YouTube Shorts keep the vertical player surface; standard YouTube and
  Bilibili videos follow the responsive conversation width.

## Live checks

1. Run `INSTALL_STABLE_V1.bat` so the pinned WebView2 bridge is installed.
2. Open a YouTube/Shorts result and confirm it plays without error 153.
3. Open a Bilibili result and confirm the HTML5 player accepts the browser.
4. Confirm the terminal reports `[INLINE VIDEO WEBVIEW2] ... ready=true` and
   `wrapper_loaded` for each platform.
5. Start a second card and confirm the first card stops and restores its cover.
