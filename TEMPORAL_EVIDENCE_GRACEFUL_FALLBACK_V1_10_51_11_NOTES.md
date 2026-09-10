# Temporal Evidence Graceful Fallback V1.10.51.11

Build ID:
`bekki-temporal-evidence-graceful-fallback-v1-10-51-11-20260904`

## Live failure reproduced

The fixed-Bilibili official search proved the correct publisher and extracted
the requested four-member facet from official 2024 videos. The exact request
was for 2022-01-15, so temporal validation correctly rejected those videos as
answers for 2022. The old all-or-nothing path then hid every useful result and
returned only LIMITED_EVIDENCE.

## Behavior

- Exact-period evidence remains the only evidence allowed to answer the target
  period or enter Knowledge under that temporal scope.
- A low-risk query may retain an explicitly dated, source-supported mismatch as
  a display-only temporal alternative.
- An explicit historical query selects the earliest dated alternative found in
  that search. A current/latest query selects the latest one.
- The reply first says that the requested period was not found, then states the
  alternative date and answer, and finally says that it does not establish the
  requested period.
- Alternative records remain `accepted=false`,
  `target_scope_answered=false`, `knowledge_capture_eligible=false`, and
  `knowledge_eligible=false`.
- Undated, wrong-entity, wrong-facet, unsupported, unverified-official, and
  medium/high-risk alternatives do not receive this fallback.

## Example

For a request asking for 2022-01-15, when only a validated official 2024 source
is found, Bekki may say that 2022-01-15 was not directly verified and show the
earliest official 2024 record found. It may not claim the 2024 roster was the
2022 roster and may not refresh the 2022/current Knowledge claim from it.

## Scope

No SQLite schema or stored document migration is required. Existing exact fact
acceptance, current-roster lifecycle normalization, official publisher identity
proof, source cards, inline playback, audio, Media Watch, and Companion Watch
remain unchanged.
