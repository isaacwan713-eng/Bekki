# Media Watch Command Lane Hotfix V1.10.47.6

Build ID: `bekki-media-watch-command-lane-hotfix-v1-10-47-6-20260902`

## Fixed

- A request to find and play a concrete title on a named website, such as
  `去 iyf.tv 播放名侦探柯南`, is kept on `SEARCH / MEDIA_WATCH`. It can no
  longer fall through to `COMMAND / DEVICE_ACTION` and the unrelated device
  content gate.
- The closed media-discovery contract reconciles both the first MAGI result
  and the independent lane-audit result. Melchior applies the same guard when
  receiving an older or externally supplied command route.
- The guard is source-agnostic: literal or verified video-site conditions are
  still extracted downstream and remain hard filters.
- Existing-player controls such as pause, resume, volume, seek, fullscreen,
  next/previous episode and reference-only requests such as `播放这个视频`
  remain outside media discovery.
- Platform searches that ask to inspect or summarize posts/videos remain
  social research instead of being converted to playback discovery.

## Compatibility

This build includes IYF Inline Playback Hotfix V1.10.47.5 and preserves its
bounded IYF direct-page player contract.
