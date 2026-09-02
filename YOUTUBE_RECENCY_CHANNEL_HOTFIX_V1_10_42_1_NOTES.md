# YouTube Recency and Channel Hotfix V1.10.42.1

Build: `bekki-youtube-recency-channel-hotfix-v1-10-42-1-20260902`

## Live-test issue fixed

The request `去油管找最近 7 天 @aespa 的 Shorts` found real Shorts cards but
returned no result because YouTube's `New` badge was passed through as the
candidate time. The RECENT pre-filter could not parse it and removed every
candidate before any video was opened.

## Changes

- `New` is explicitly treated as a badge, never as a date.
- A relevant YouTube card with no visible date proceeds provisionally to the
  opened-video stage.
- The opened video's publication metadata is mandatory for an unresolved
  RECENT candidate; missing or out-of-window dates fail closed.
- Exact `@handle Shorts` requests open the channel's own `/@handle/shorts` tab
  instead of a general YouTube search.
- The opened video's channel handle is extracted and compared exactly with the
  requested handle.
- A channel-owned tab can provide the same handle boundary only after the video
  was successfully opened; a general results page cannot use this fallback.
- The opened video's real channel name replaces any search-model author value.
- Third-party videos that merely mention `aespa`, `#aespa` or `@aespa` are
  excluded from an `@aespa` channel request.

## Retest

`去油管找最近 7 天 @aespa 的 Shorts`
