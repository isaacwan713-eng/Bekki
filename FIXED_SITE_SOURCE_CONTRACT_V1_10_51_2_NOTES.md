# Bekki Fixed Site Source Contract V1.10.51.2

Build ID: `bekki-bilibili-native-fact-executor-v1-10-51-3-20260903`

This data-preserving routing release separates a request's semantic purpose
from its required web source. SQLite remains schema version 2. No Knowledge
document, event stream, JSON/JSONL mirror, or migration snapshot is rewritten.

## Contract

- `search_scope` answers **what** Bekki must do: `FACT_LOOKUP`, `CLAIM_CHECK`,
  `SOCIAL_RESEARCH`, `MEDIA_WATCH`, or another existing purpose.
- `source_scope` answers **where** research may occur: `OPEN_WEB` or
  `FIXED_SITES`.
- `requested_sites` contains normalized public domains explicitly bound to a
  search instruction, such as `bilibili.com`, `youtube.com`, or
  `wikipedia.org`.
- `official_only` is a separate evidence policy and is never inferred merely
  because a site was named.

Examples:

- “去 B 站核实当前成员，只看官方账号” becomes `FACT_LOOKUP` plus fixed
  `bilibili.com` and `official_only=true`.
- “去 B 站看看大家怎么评价” remains `SOCIAL_RESEARCH` plus fixed Bilibili.
- “去 YouTube 找这个视频播放” remains `MEDIA_WATCH` plus fixed YouTube.
- “去 Wiki 查背景” becomes `FACT_LOOKUP` plus fixed `wikipedia.org`.

## Safety behavior

- A site mention without a source instruction, such as “B站是什么公司？”, does
  not constrain discovery.
- Domains are normalized and limited to public hostnames; exact hosts and their
  subdomains match, lookalike domains do not.
- Fixed-source fact discovery and all follow-up searches are domain-filtered.
- External-model fallback is disabled for a fixed-source lookup because it
  cannot prove that its answer came from the requested site.
- Official-only claim checks use the page-validating fact browser. An
  official-only social summary stops safely until publisher identity can be
  enforced by that executor.
- Unsupported purpose/source combinations return `SOURCE_SCOPE_UNSUPPORTED`
  instead of widening to the open web.

## Expected live rerun

The official-Bilibili member verification should print:

`[MAGI SOURCE/PURPOSE SEPARATED] purpose=FACT_LOOKUP sites=bilibili.com`

followed by a valid `[MAGI ROUTE]` containing `source_scope: FIXED_SITES`, then:

`[MELCHIOR FIXED SOURCE ROUTE] FACT_LOOKUP sites=bilibili.com official_only=True`

and:

`[CASPER FIXED SOURCE] sites=bilibili.com official_only=True`

It must not print `MAGI INVALID ROUTE` or route the fact request through
`MELCHIOR SOCIAL ROUTE`.

Run the isolated regression suite with:

`powershell -ExecutionPolicy Bypass -File .\TEST_FIXED_SITE_SOURCE_CONTRACT_V1_10_51_2.ps1`
