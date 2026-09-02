# Social Relevance Scope V1.10.29

Build: `bekki-social-relevance-scope-v1-10-29-20260830`

## Outcome

- Social Query's existing Gemma call now returns the query, `RECENT` or
  `RELEVANCE`, and an optional day window together.
- A request without an explicit time condition uses `RELEVANCE`; Bekki does
  not silently impose the former seven-day window.
- An explicit request such as “最近一周” still uses strict seven-day date
  validation.
- Relevance mode retains old and undated posts and ranks visible evidence by
  support for the complete request. Visible interaction is secondary.
- Relation searches favor visible posts connecting all requested entities over
  popular posts about only one adjacent entity.
- Bilibili, Reddit, Xiaohongshu, Instagram, and X use their actual display
  names in replies. The direct renderer no longer assumes Xiaohongshu.
- Bilibili and Reddit native search sorting follows the same AI-owned scope.
- No additional AI role, arbitration gate, or Python semantic classifier was
  added.

## Verification

Deterministic regression:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: 912 tests pass, with 28 opt-in live tests skipped.

Focused deterministic contract:

```powershell
python -m unittest -v tests.test_social_relevance_scope_v1_10_29
```

Live Gemma scope contract:

```powershell
$env:BEKKI_LIVE_AI_TESTS="1"
python -m unittest -v tests.test_live_ai_contracts.LiveAIContractTests.test_social_query_time_scope_contract
Remove-Item Env:BEKKI_LIVE_AI_TESTS
```

The no-time Bilibili example must return `RELEVANCE` with
`recency_days=null`; the “最近一周” example must return `RECENT` with
`recency_days=7`.
