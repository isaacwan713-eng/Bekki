# Bekki R17 recommendation model handoff

Build ID: `bekki-skills-v1-20260818-r17`

R17 fixes the live R16 failure where Melchior routed the request correctly but
the next two `gemma3:12b` recommendation-plan calls both terminated with
Windows exit `0xc0000409` and `CUDA error: shared object initialization failed`.
The managed browser never started because planning occurs before discovery.

For product recommendations, Bekki now:

1. lets gpt-oss complete the main Melchior route;
2. releases `gemma3:12b` and `llama3.2:latest`;
3. loads the already-required `gemma3:12b` model for the AI-owned recommendation
   plan and editorial-source synthesis;
4. releases Gemma before later chat/context work resumes.

Gemma—not Python—still decides the complete product topic, explicitly stated
criteria, search queries, eligible engines, result count, ranking, and summary.
R17 does not restore shopping-planner or Python category gates to ordinary
recommendations. Explicit purchase, price, stock, seller, and purchase-link
requests still use the separate strict shopping route.

Acceptance request: `给我推荐几个吸管杯`

Expected logs include model-unload messages followed by:

- `[CASPER AI RECOMMENDATION PLAN]`
- `[CASPER RECOMMENDATION SOURCE]`
- `[CASPER AI RECOMMENDATION OPTIONS]`

The recommendation path must not show shopping-plan, merchant-discovery, or
product-page verification logs.
