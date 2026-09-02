# Inline Social Video Compatibility Hotfix V1.10.43.1

Build: `bekki-inline-social-video-compat-hotfix-v1-10-43-1-20260902`

## Fixed

- Replaces the one-shot top-level player request with a verified local wrapper
  document and an in-card iframe carrying a real HTTPS referrer policy.
- Adds YouTube `origin` and `widget_referrer` identity parameters to prevent
  player configuration error 153 in QtWebEngine.
- Installs one profile-level request interceptor so YouTube and Bilibili iframe
  and media subrequests retain the correct platform Referer.
- Removes only the `QtWebEngine/<version>` product token from the profile's
  native Chromium user agent, avoiding false unsupported-browser detection
  without hard-coding a fake browser version.
- Logs H.264, VP9 and AV1 `canPlayType` support after each wrapper load. This
  distinguishes a page/referrer failure from a QtWebEngine build that lacks a
  proprietary media codec.

## Preserved behavior

- Players remain absent and paused until the user clicks `在 Bekki 播放`.
- Playback stays inside the result card; no player popup or replacement page is
  opened.
- Only one card can play at a time, and `停止播放` restores its evidence cover.
- URL, host, path and video-ID validation remains fail-closed.
- The WebEngine profile remains memory-only with no persistent cookies.

## Live checks

1. Open one YouTube or Shorts result and confirm error 153 no longer appears.
2. Open one Bilibili result and confirm the HTML5 player is accepted.
3. Check the terminal for a line beginning `[INLINE VIDEO CODECS]`.
4. If Bilibili still reports no HTML5 player and that line shows an empty H.264
   value, the installed QtWebEngine runtime lacks H.264; use a WebView2 or native
   media backend in the next update rather than changing the search/card logic.
