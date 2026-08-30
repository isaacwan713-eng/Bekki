# Bekki Knowledge Breadth and Historical Snapshots V1.10.20

Build ID: `bekki-knowledge-breadth-history-v1-10-20-20260829`

## What changed

- The existing Curiosity Writer now receives bounded related Knowledge as well
  as recent curiosity history and declares `topic_stage`, current-turn depth,
  proposed-question depth, and exact supporting record IDs.
- New or sparse topics begin with approachable foundation knowledge such as
  people, history, works, events, stories, relationships, culture, or ordinary
  behavior. Specialist follow-ups remain available when the user is already
  discussing the topic at specialist depth or sustained related history
  supports the step.
- Completed historical people rosters can enter Knowledge as `FIXED_HISTORY`
  only with an exact closed date or season. The period is stored in
  `temporal_scope` and participates in the knowledge identity.
- Historical snapshots from different periods remain separate during daily
  curation and cannot conflict or deduplicate merely because they share an
  entity or roster facet.
- MAGI may use a historical roster only for the exact same completed period.
  Current/active people rosters still route to search and never enter
  Knowledge. Formal organizational-unit inventories retain their existing
  stable/reviewable lifecycle.

## Architecture boundary

No AI role, gate, arbiter, external request, domain keyword classifier, or
model call was added. The existing Writer, lifecycle governors, curator, and
MAGI make the semantic decisions. Python bounds supplied records, validates
declared IDs and lifecycle metadata, and prevents a fixed-history record from
being stored without an exact closed period.

## Verification

- Deterministic suite: 850 tests passed; 22 opt-in live-model tests skipped.
- Added opt-in live contracts for curiosity depth, historical-vs-current
  roster lifecycle, and exact-period MAGI routing.

