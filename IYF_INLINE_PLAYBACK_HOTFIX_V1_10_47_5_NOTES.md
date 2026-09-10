# IYF Inline Playback Hotfix V1.10.47.5

Build ID: `bekki-iyf-inline-playback-hotfix-v1-10-47-5-20260902`

## Fixed

- Verified `iyf.tv` `/play/<show-id>` results now receive a real inline-video
  contract, so cards expose `在 Bekki 播放` and `影院模式` instead of remaining
  link-only.
- The original IYF HTML5 player is loaded directly inside Bekki's WebView2
  host. Queryless show pages may select their default episode, and explicit
  `?id=<episode-id>` pages preserve the requested episode.
- Navigation is fail-closed: only HTTPS episode pages for the same selected
  show and approved IYF host aliases are accepted. Other shows, search/catalog
  pages, external domains, fragments and unexpected query parameters are
  rejected.
- Direct third-party pages do not receive Bekki's companion JavaScript bridge.
  `Bekki 陪看` is therefore disabled for IYF in this build, while the existing
  YouTube and Bilibili wrapper players are unchanged.
- An exact requested series title outranks related movies or specials during
  media-watch selection.

## Compatibility

This build includes IYF Native Candidate Hotfix V1.10.47.4. The IYF native
search and duplicate-anchor merging behavior from that build is unchanged.
