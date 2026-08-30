# Bekki Knowledge-Aware Routing and Adjacent Curiosity V1.10.19

Build ID: `bekki-knowledge-aware-curiosity-v1-10-19-20260829`

## Knowledge-aware routing

- Active Knowledge is now recalled before MAGI, not after routing.
- The existing MAGI call receives a compact view of the same candidates used
  by the final answer and returns `local_knowledge_sufficiency` as
  `SUFFICIENT`, `PARTIAL`, or `NONE`.
- MAGI owns semantic sufficiency across entity, relation, time scope, and all
  requested facets. Python validates only the closed contract and candidate
  presence.
- `SUFFICIENT + LOCAL` is honored directly by Melchior, so a repeated question
  already covered by active Knowledge does not enter 3-5-7 research again.
- Explicit requests for fresh web verification, partial matches, and transient
  facts outside the stored claim's scope continue to use SEARCH.
- Candidate recall occurs once per turn and adds no model call. A sufficient
  route also skips the compact Melchior routing call.

Expected diagnostic order:

```text
[KNOWLEDGE FAST CONTEXT] items=1
[MAGI ROUTE] ... "lane":"LOCAL" ... "local_knowledge_sufficiency":"SUFFICIENT"
[MELCHIOR KNOWLEDGE ROUTE] LOCAL_ANSWER
```

## Adjacent curiosity

- The existing Curiosity Writer receives at most 20 prior public curiosity
  questions as bounded local history.
- First exposure stays near the central topic and the user's apparent level.
- Comparisons and deeper mechanisms follow familiarity.
- Contracts, governance, business operations, and specialist mechanisms are
  reserved for explicit or sustained deeper interest.
- No Python topic classifier, semantic keyword rule, new AI role, or new model
  call was added.

## Verification

- Deterministic suite: 835 tests passed; 19 opt-in live tests skipped.
- New opt-in Gemma contract:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_active_local_knowledge_routes_repeated_fact_to_local
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```
