# Bekki Bilibili Native Fact Executor V1.10.51.3

Build ID: `bekki-bilibili-native-fact-executor-v1-10-51-3-20260903`

This data-preserving release adds the first site-native executor beneath the
V1.10.51.2 purpose/source contract. SQLite remains schema version 2. It does
not rewrite Knowledge, NERV state, mirrors, or migration snapshots.

## Live failure addressed

The prior live rerun correctly preserved `FACT_LOOKUP`, fixed the source to
`bilibili.com`, and enforced `official_only=true`. Its executor nevertheless
used Google/Bing web discovery. Those engines returned Bilibili's homepage,
ranking, app, live, and manga pages rather than the requested official account
or material. Follow-up queries also accumulated duplicate `site:bilibili.com`
operators.

## Native behavior

- A fact lookup fixed exactly to Bilibili opens Bilibili's own search UI.
- Bounded native-response video rows and rendered video cards are retained.
- Rendered Bilibili account/profile cards are additionally retained only for
  fact lookup; existing social-search candidate rules remain unchanged.
- At most three account candidates are placed before a bounded mix of video
  candidates, preventing either candidate type from consuming the whole read
  budget.
- Video pages use the existing bounded current-video reader, excluding the
  recommendation rail. Account pages use the exact rendered profile URL.
- Every answer still passes temporal scope, entity scope, completeness,
  source support, and the independent official-publisher audit.
- If native discovery returns nothing or fails, the fixed Bilibili lookup does
  not widen to ordinary web search or External AI.

## Query safety

The fixed-source query function removes every preexisting `site:` operator,
including unapproved or duplicate domains, before applying exactly one
canonical approved constraint. Native search then removes the web-engine
operator and a redundant leading `Bilibili`/`B站` label.

## Expected live logs

The same official-member request should retain the V1.10.51.2 route logs and
then add:

`[CASPER NATIVE FACT SEARCH] platform=bilibili ... candidates=N`

The browser search log must not contain:

`site:bilibili.com site:bilibili.com`

Run:

`powershell -ExecutionPolicy Bypass -File .\TEST_BILIBILI_NATIVE_FACT_EXECUTOR_V1_10_51_3.ps1`
