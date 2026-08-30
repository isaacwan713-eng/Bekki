# News Feed Reliability V1.4

Build: `bekki-news-feed-reliability-v1-4-20260827`

## Fixes

- `这几个月`, `最近几个月`, and equivalent English requests resolve to one
  bounded recent date window anchored to the current local date.
- If the query model introduces a year outside that window, both queries are
  rebuilt from the original request and authoritative start/end dates.
- Invalid news-extraction JSON triggers one smaller schema-constrained retry.
- A second extraction failure becomes `LIMITED_EVIDENCE`; Casper and the final
  response no longer report successful completion or claim there was no news.

## Regression

- The observed SNH48 query that expanded to `August 2023 - August 2026` is
  forced back to `2026-04-25` through `2026-08-27` for the 2026-08-27 test.
- The observed narrative English extractor output is simulated as an invalid
  JSON contract, followed by a successful structured recovery.
- Fail-closed final wording explicitly distinguishes extraction failure from
  an evidence-backed finding of no concrete news.
