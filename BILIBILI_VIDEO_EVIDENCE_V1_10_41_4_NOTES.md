# Bilibili Video Evidence V1.10.41.4

Build: `bekki-bilibili-video-evidence-v1-10-41-4-20260901`

## What changed

- Bilibili cards now prefer the current video's native cover image.
- Bekki attempts one bounded muted player decode and keeps the sampled frame
  only when it is visibly non-black and distinct from the cover.
- Black players, loading glyphs, duplicate frames and nearly blank rasters are
  rejected before they reach the model or UI.
- Bilibili no longer adds a full video-page/container screenshot labeled
  `正文`; that image was dominated by navigation and related-video chrome.
- Current-video understanding is limited to title, UP author, publication time
  and description metadata. The recommendation rail is excluded.
- The multimodal prompt treats a cover as a cover and one sampled frame as one
  moment, never as a transcript or full-video summary.

## Unchanged

- Xiaohongshu keeps up to three post images plus one text capture.
- Reddit keeps one post-body capture.
- The shared minimized browser profile, login state, Gemma 4 12B model and
  8192-token social context remain unchanged.

