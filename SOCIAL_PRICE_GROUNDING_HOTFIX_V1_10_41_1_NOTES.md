# Social Price Grounding Hotfix V1.10.41.1

Build: `bekki-social-price-grounding-hotfix-v1-10-41-1-20260901`

This hotfix corrects the failed Xiaohongshu Karina card-price test without
raising Bekki's model or browser budget.

## Fixed

- Search-page interaction values are excluded from PRICE evidence unless the
  captured post text explicitly binds the same amount to a price marker.
- PRICE cards and rankings require grounded price observations; likes or a
  generic interaction value can no longer create a price card.
- Unknown-currency shorthand remains readable, including `330💼`, `卡价 250`,
  `190`, and `1.9k` when the visible listing context establishes a price.
- PRICE synthesis is deterministic. It never asks the model to reinterpret
  interaction numbers, and it leaves post-specific prices, images, and links
  inside their matching cards.
- Karina requests activate a bounded verified alias group covering `Karina`,
  `柳智敏`, `柚卡`, and `纯柚`. No unrelated aliases may be inferred.
- A detached Xiaohongshu title receives one atomic fresh-DOM click retry before
  the existing fallback path.

## Runtime budget

- `gemma4:12b` remains the social understanding model.
- Social model context remains `8192` tokens.
- Xiaohongshu and Reddit screenshot limits are unchanged.
- The persistent minimized unified browser profile is unchanged.
- The 16 GB VRAM operating target remains unchanged.
