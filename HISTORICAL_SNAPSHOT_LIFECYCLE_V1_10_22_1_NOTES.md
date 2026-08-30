# Bekki Historical Snapshot Lifecycle Calibration V1.10.22.1

Build ID: `bekki-historical-snapshot-lifecycle-v1-10-22-1-20260830`

This hotfix corrects the real Gemma contract failure found by
`test_audited_fact_lookup_historical_snapshot_partition_contract`.

- The previous lifecycle prompt said `proposed_persist` was advisory, but its
  JSON schema description incorrectly told the auditor to keep persistence
  false when the first partitioner withheld it.
- The unified contract now states that an exact people-roster snapshot tied to
  a completed past date or closed season is FIXED_HISTORY. Future joins,
  departures, transfers, or organizational closure cannot change who was on
  the roster at that recorded time.
- The first partitioner is explicitly told not to classify a dated historical
  snapshot as changing merely because it contains people.
- The existing lifecycle auditor is explicitly authorized to correct an
  earlier `changing + persist=false` proposal to
  `FIXED_HISTORY + stable + persist=true` when the claim, temporal metadata,
  source-supported period, and existing safety contract all agree.
- Current, ongoing, open-ended, ambiguously dated, or unsupported people
  rosters remain transient and never enter Knowledge.
- The host-local date is supplied as temporal authority so the model does not
  rely on an assumed training date.
- No new AI role, model call, factual gate, Python semantic classifier, or
  synchronous response delay was introduced.
