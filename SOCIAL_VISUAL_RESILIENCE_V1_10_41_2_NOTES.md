# Social Visual Resilience V1.10.41.2

Build: `bekki-social-visual-resilience-v1-10-41-2-20260901`

This patch keeps Xiaohongshu price research useful when a foreground game
temporarily prevents Ollama from loading the local vision model.

## Fixed

- PRICE searches skip the optional search-page overview vision call. Other
  overview-vision failures return an empty optional evidence block and do not
  abort post resolution, screenshots, text evidence, cards or links.
- Deterministic title parsing can still build an evidence card when post-level
  model understanding is unavailable. Supported marketplace forms now include
  `30👝`, `35🍞`, `均7/1`, and `330💼`; absent currencies remain explicitly
  unknown.
- `柚小卡` is included in the request-scoped verified alias group for Karina.
- Xiaohongshu result titles can be re-read directly from the live DOM after a
  reactive node replacement, preserving the card crop and post URL when
  available.
- Image-heavy PRICE responses use compact narrative fields while keeping up to
  ten distinct price observations, reducing malformed JSON caused by response
  truncation.
- Platform search URLs are navigation context only. They no longer render as
  duplicate empty “小红书”, Reddit, Bilibili, X or Instagram source cards.

## Runtime budget

- `gemma4:12b` remains the social understanding model.
- Social model context remains `8192` tokens.
- Xiaohongshu keeps up to three post images plus one body capture; Reddit keeps
  one body capture.
- The persistent minimized unified browser profile is unchanged.
- The 16 GB VRAM coexistence target is unchanged. A driver/Ollama CUDA failure
  itself cannot be eliminated here, but optional visual failure no longer
  clears already collected evidence.

## Suggested Windows check

Run the same Karina card-price request while Genshin Impact is open. If Ollama
cannot accept an optional visual request, Bekki should still finish with any
resolved post cards, locally captured evidence images, prices found in titles,
and concrete original-post links. It must not replace them with generic empty
platform cards.
