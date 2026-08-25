# Bekki R20 US-only search contract

Build ID: `bekki-skills-v1-20260818-r20`

R20 keeps the R19 lightweight runtime and narrows browser discovery to the
environment Bekki currently needs.

## Active search boundary

- Supported engines: Google and Bing only.
- Primary engine: Google.
- Fallback engine: Bing, only when Google fails or returns too few usable
  results for the current evidence stage.
- Supported request languages: Chinese and English through the same US-oriented
  search pair.
- Country codes, query language, and stale context cannot activate Naver,
  Baidu, Sogou, DuckDuckGo, Bing China, Yahoo Japan, or Yandex.
- Search-engine selection is deterministic and makes zero model calls.

AI continues to decide the research topic, query wording, recommendation
criteria, candidate selection, verification, and final comparison. Python owns
only the fixed engine boundary, result budget, fallback threshold, safety, and
browser execution.

## Acceptance checks

For either `给我推荐几个吸管杯` or `recommend a few straw cups`, the console
should show:

`[CASPER SEARCH ENGINES FIXED_US] ('google', 'bing')`

If Google provides enough results, there should be no fallback line. If it is
insufficient, the next line may show:

`[CASPER BROWSER SEARCH FALLBACK] bing ...`

The full project test suite should no longer expect Korean, Chinese, or other
regional search-engine plans.
