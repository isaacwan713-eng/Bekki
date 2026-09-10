# Knowledge Relationship Temporal Scope V1.10.51.7

Build ID: `bekki-knowledge-relationship-temporal-scope-v1-10-51-7-20260904`

## Live finding

The verified 四禧丸子 current roster and the fixed 2022 roster correctly
merged into four deduplicated `member -> member_of -> group` edges. Each edge,
however, had one expiring current support and one permanent closed-historical
support. The old `active` projection meant "some supporting Knowledge is
active," so after the current roster expired the 2022 evidence could leave the
unqualified edge visible to a future present-state caller.

## Temporal relationship contract v2

- Keep the semantic relationship ID unchanged and retain every provenance row.
- Partition support into current and closed-historical sets from each verified
  claim's normalized `temporal_scope`.
- Make `load_topic_relationships()` default to `temporal_view="current"`.
- Allow explicit `historical` and `all` views for past-period research and
  auditing.
- Expose current, historical, and all active support IDs separately.
- Label each edge `CURRENT_ONLY`, `HISTORICAL_ONLY`,
  `CURRENT_AND_HISTORICAL`, or `INACTIVE`.
- Keep the complete Topic catalog on the `all` view while carrying explicit
  temporal status, so lifecycle and curation retain historical coverage.
- Upgrade relationship contract v1 documents in place without changing edge
  IDs, claims, evidence, SQLite schema, or rollback mirrors.

## Safety boundary

A closed historical relationship remains queryable forever as history, but it
cannot by itself appear in the default current relationship view. Unscoped or
`CURRENT_ACTIVE_STATE` support remains current according to its own stable or
reviewable lifecycle. The patch does not infer whether any person currently
belongs to another organization.

## Unchanged

Browser routing, Bilibili evidence capture, inline playback, audio, WebView2,
UI, and Companion Watch are byte-for-byte outside this patch's scope.
