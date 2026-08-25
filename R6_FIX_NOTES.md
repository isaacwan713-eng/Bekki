# Bekki R6 hotfix

Build ID: `bekki-skills-v1-20260818-r6`

R6 fixes the failures reproduced in the R4/R5 runtime log:

- Windows Recycle Bin actions are treated as a bounded built-in device surface.
  A secondary content model can no longer widen `打开回收站` into browser-based
  content learning.
- The content-learning planner rejects non-`game_content.*` capabilities before
  web discovery.
- Product recommendation and shopping requests use the verified product-page
  controller.
- Shopping query planning uses the compact local model with a genuinely compact
  retry. Empty AI output fails closed instead of searching the raw Chinese user
  sentence.
- Yandex is disabled for unattended search because it repeatedly requests
  CAPTCHA verification. Browser discovery gets one bounded global-engine
  recovery attempt.
- A CAPTCHA from one merchant is skipped during a regional multi-merchant search;
  it only becomes a handoff when the user explicitly requested that merchant.
- Zero verified product cards produce a deterministic no-results message. Bekki
  does not invent product names, sizes, prices, or specifications.
- A failed best-effort conversation-context update no longer discards an already
  generated reply.
- Ollama HTTP failures now log the response status, model, context/output budget,
  and a bounded local error message.
- The final chat response budget is reduced to 16K context / 4K output for more
  headroom on a 16 GB GPU.

After installation, start Bekki from the project root with `python main.py` and
confirm the console prints:

`[BEKKI BUILD] bekki-skills-v1-20260818-r6`

Acceptance requests:

1. `打开回收站`
2. `给我推荐三个杯子`
3. `帮我在网上找三个不锈钢杯子`

The first request must open the local Recycle Bin without a web search. Product
requests must return verified cards or an explicit no-verified-results message;
they must never fabricate three generic products.
