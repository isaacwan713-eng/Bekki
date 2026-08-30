# NERV Context Isolation V1.3

Build: `bekki-nerv-context-isolation-v1-3-20260827`

## Fix

- A self-contained current message no longer receives prior conversation text
  in Melchior's main router, recovery router, lane recovery, MAGI audit, or the
  focused content-action audit.
- Recent conversation is exposed only when the current message contains an
  explicit unresolved reference such as `这个`, `刚才那个`, `第二个`,
  `continue`, or `the previous one`.
- The explicit `NERV_LEARNING` inventory guard from V1.2 remains active.

## Regression

- The current message `你知道我以前住在SNH48新梦剧场边上吗？` is tested
  against stale context about Shohei Ohtani's sweeper. The router packet must
  contain SNH48 and must not contain the Ohtani claim.
- A genuine follow-up such as `那这个是真的吗？` still receives the recent
  topic so reference resolution continues to work.
