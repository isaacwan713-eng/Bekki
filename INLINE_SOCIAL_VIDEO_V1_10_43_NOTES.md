# Inline Social Video V1.10.43

Build: `bekki-inline-social-video-v1-10-43-20260902`

## What changed

- Adds in-card playback for verified YouTube videos, YouTube Shorts and
  Bilibili video URLs.
- Keeps every card as a static, paused cover until a deliberate click on
  `在 Bekki 播放`.
- Creates the player inside the existing result card instead of opening a new
  page or popup.
- Allows only one active player; starting another stops and disposes the prior
  player and restores its evidence cover.
- Uses a vertical bounded surface for Shorts and responsive 16:9 sizing for
  ordinary YouTube and Bilibili videos.
- Blocks popup creation and main-frame navigation outside the exact verified
  embed target.
- Uses an off-the-record WebEngine profile with memory-only cache and no
  persistent cookies.
- Retains `打开原帖` as a separate explicit fallback.
- Keeps Bekki usable when QtWebEngine is unavailable; only inline playback is
  omitted in that environment.

## Regression coverage

- Strict host, HTTPS, port, path and video-ID validation.
- YouTube watch, Shorts, live and `youtu.be` canonicalization.
- Bilibili BV-video canonicalization.
- Rejection of channel, playlist, search and lookalike-host URLs.
- Bound-player navigation and popup restrictions.
- Root/runtime UI and video-contract mirrors.
- PyInstaller QtWebEngine hidden-import coverage.

## Suggested live checks

1. Run `去油管找最近 7 天 @aespa 的 Shorts`.
2. Confirm every card initially shows only its static cover.
3. Click `在 Bekki 播放` and verify the Short plays vertically inside that card.
4. Start a second card and verify the first player disappears and stops audio.
5. Click `停止播放` and verify the original preview images return.
6. Search for a Bilibili video and repeat the same playback checks.
