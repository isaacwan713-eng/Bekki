# YouTube Social Evidence V1.10.42

Build: `bekki-youtube-social-evidence-v1-10-42-20260901`

## What changed

- Adds YouTube/油管 as a first-class `SOCIAL_RESEARCH` platform.
- Preserves literal queries, channel names, `@handles`, video IDs and explicit
  Shorts intent.
- Discovers standard video, Shorts and live-video cards while rejecting
  channels, playlists, navigation links and unrelated watch targets.
- Canonicalizes `watch`, `shorts`, `live` and `youtu.be` URLs by video ID.
- Reads only current-video title, channel, publication date and description.
- Reconciles search-card dates with authoritative metadata from the opened
  video.
- Captures at most one native thumbnail and one distinct decoded player frame.
- Rejects ads, black/loading frames, recommendations, comments and generic
  full-page screenshots.
- Dismisses only a bounded YouTube cookie-choice prompt and never touches
  sign-in controls.

## Regression coverage

The release includes focused YouTube contracts plus the existing Bilibili,
Xiaohongshu, discussion-feed and runtime regression suites.

## Suggested live checks

1. `去 YouTube 搜索 aespa live clips，列出最相关的 3 个视频`
2. `去油管找最近 7 天 @aespa 的 Shorts`
3. Verify that every card opens the same video shown by its title and image.
4. Verify that video cards show a clear thumbnail and, when available, one
   useful player frame rather than a full-page screenshot.
