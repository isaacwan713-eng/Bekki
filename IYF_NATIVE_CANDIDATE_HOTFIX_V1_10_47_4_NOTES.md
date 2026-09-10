# IYF Native Candidate Hotfix V1.10.47.4

Build ID: `bekki-iyf-native-candidate-hotfix-v1-10-47-4-20260902`

## Fixed

- Catalog anchors that point to the same detail URL are merged before candidate
  conversion. A later heading can replace an earlier empty cover link while
  retaining the cover image.
- Episode numbers, time/duration labels, icon-only strings and generic controls
  such as `立即播放` are rejected as video titles.
- One best native candidate is retained for each canonical detail URL, so the
  `iyf.tv` result titled `名侦探柯南` reaches topic scoring instead of falling
  through to web search.
- Rejected media-watch candidates emit a bounded diagnostic reason such as
  `topic_miss`, `site_mismatch`, or `derived_content`.
- `.cache/` and `.lesshst` are ignored so local Codex/runtime files are not
  added to later Git commits.

## Compatibility

This build includes Verified Video Site + Companion Bridge Hotfix V1.10.47.3.
Verified sites without a supported Bekki player contract remain honest
link-only cards; this patch does not claim that `iyf.tv` can play inline.
