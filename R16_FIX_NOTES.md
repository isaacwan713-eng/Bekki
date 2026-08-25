# Bekki R16 gpt-oss recommendation JSON compatibility

Build ID: `bekki-skills-v1-20260818-r16`

R16 preserves R15's AI-owned recommendation architecture and fixes the exact
live failure where Ollama returned `done_reason=stop` with empty `thinking` and
empty `response` twice for `casper_product_recommendation_plan.txt`.

The cause was forcing an Ollama JSON Schema on `gemma3:12b`. Bekki's existing
model-call contract already documents that forcing JSON mode can suppress valid
gpt-oss output. R16 removes schema forcing from both the recommendation-plan
and recommendation-synthesis calls. The prompts still require one JSON object,
and the existing parser still handles normal JSON and fenced JSON safely.

Both AI stages get one plain-JSON retry. No Python product-category, feature,
popularity, count, ranking, or recommendation judgement has been reintroduced.
The strict shopping route remains unchanged.

Acceptance request: `给我推荐几个吸管杯`

Expected log progression:

- `[CASPER AI RECOMMENDATION PLAN]` with topic `straw cup`
- `[CASPER RECOMMENDATION SOURCE]`
- `[CASPER AI RECOMMENDATION OPTIONS]`

The recommendation path must not show shopping-plan, merchant-discovery, or
product-page verification logs.
