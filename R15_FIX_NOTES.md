# Bekki R15 AI-owned product recommendations

Build ID: `bekki-skills-v1-20260818-r15`

R15 removes the shopping planner from ordinary product recommendations.

For requests such as `给我推荐杯子` or `给我推荐几个吸管杯`, one capable AI now
owns the complete recommendation topic, any explicitly stated criteria, the
editorial search queries, eligible search-engine choice, desired result count,
ranking, and final summary. Python no longer translates product categories,
promotes inferred features into requirements, applies popularity gates, or
semantically rejects the AI's category decision. Its recommendation-path role
is limited to execution, JSON structure, bounded resources, and binding cited
source indexes to UI cards.

The strict `build_shopping_plan` contract remains only for explicit purchase,
price, stock, seller, and purchase-link requests. Recommendation research still
ends at independent reviews, comparisons, and reputable roundups; it does not
open merchant product pages.

R15 also catches one transient Ollama/CUDA failure at the primary Melchior
router boundary, unloads the compact model best-effort, and asks the AI router
once more with the existing compact recovery prompt.

Acceptance requests:

- `给我推荐杯子`
- `给我推荐几个吸管杯`
- `给我推荐三个网红牌子杯子`
- `查一下这个杯子的价格和库存`

The first three must show `[CASPER AI RECOMMENDATION PLAN]` and must not show
shopping-planner, merchant-discovery, or product-page verification logs. The
last request must use the separate shopping route.
