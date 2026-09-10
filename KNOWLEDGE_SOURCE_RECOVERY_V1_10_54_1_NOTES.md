# Knowledge Source Recovery V1.10.54.1

Build: `bekki-knowledge-source-recovery-v1-10-54-1-20260906`

## What this fixes

The first live V1.10.54 cycle correctly selected `akb48_ecosystem`, but its
three source candidates produced one rejection, one HTTP 403, and one timeout.
The run therefore verified no claim while its legacy result label still said
`COMPLETED`. It also exposed a case-sensitive topic/source match that could
hide an approved `akb48` source from an `AKB48` lifecycle Topic.

## Source recovery

- Topic/source matching now uses one case-insensitive identity function.
- Primary discovery searches for an official site or primary source first.
- If no readable source is approved, one bounded fallback searches from the
  clean Topic title for an established reference or organizational history.
- Results are ranked before review, but deterministic ranking never approves a
  source; the existing Source Judge remains the trust boundary.
- Official and institutional candidates are reviewed before generic pages.
  Once a high-quality source is approved, low-accountability leftovers are not
  retried during that cycle.
- A rejected domain is excluded from later discovery under the same source
  policy. HTTP/read failures receive a 24-hour URL retry timestamp, and only
  one URL per domain is attempted in a cycle.
- Up to three distinct pages per domain may be retained, allowing an
  inaccessible page to coexist with a different potentially readable page.

## Honest outcomes and retries

- A run with no verified, updated, duplicate, or verified transient outcome is
  recorded as `NO_VERIFIED_EVIDENCE`, not `COMPLETED`.
- Existing V1.10.54 rows that said `COMPLETED` while all evidence counters were
  zero are interpreted as no-evidence attempts in memory; SQLite history is not
  rewritten.
- An open Topic with no evidence may retry after 24 hours instead of waiting
  the normal seven-day success cooldown.
- A failed profile fallback also waits 24 hours, preventing the ten-minute
  desktop due check from creating a retry loop.
- The profile fallback cannot bypass a lifecycle Topic's retry cooldown.

## Validation

Close Bekki, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_SOURCE_RECOVERY_V1_10_54_1.ps1
```

To inspect the next plan without research:

```powershell
python knowledge_scheduler.py plan
```

To intentionally retry immediately rather than waiting for the 24-hour
no-evidence cooldown:

```powershell
python knowledge_scheduler.py run --force
```

## Unchanged scope

This release does not change Bilibili navigation, UP profile rendering,
playback, video quality, UI fonts, or Companion Watch output.
