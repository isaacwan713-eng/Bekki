# IYF Companion Watch Hotfix V1.10.47.7

Build ID: `bekki-iyf-companion-watch-hotfix-v1-10-47-7-20260902`

## Fixed

- Verified IYF direct-page players now enable the theater toolbar's
  `Bekki 陪看` action.
- Bekki installs its own lower-right input/reply panel after every permitted
  IYF page or episode navigation, so the feature does not depend on the
  source site's DOM or player controls.
- The IYF panel uses the same frame-capture and companion-model pipeline as
  Bilibili and YouTube. Direct questions still use the detail model and
  automatic reactions remain deduplicated.

## Boundary

- Injection is limited to a rebuilt, verified `iyf.tv` playback contract.
- The UI is isolated in a closed shadow root and uses a randomized 96-bit
  token (24 hexadecimal characters) in the qtwebview2 RPC method for each
  player instance.
- Events are accepted only while that exact card owns the current theater
  and Companion Watch session. Messages remain capped at 320 characters.
- Existing same-show episode navigation, popup blocking, download blocking,
  one-active-player cleanup and audio behavior are unchanged.

This build includes Media Watch Command Lane Hotfix V1.10.47.6.
