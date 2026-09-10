# Current Roster Lifecycle Normalization V1.10.51.9

Build ID: `bekki-current-roster-lifecycle-normalization-v1-10-51-9-20260904`

## Live failure reproduced

An accepted current-roster search reached the independent lifecycle audit, but
the model returned a maintained-set explanation with these incompatible JSON
fields:

```text
knowledge_type = stable
valid_for_days = null
```

The safety contract correctly failed closed with
`current_roster_must_be_reviewable`, so no bad row was written. The accepted
search could not refresh the already stored roster, however.

## Fix

- After normal evidence, confidence, and persistence eligibility checks, an
  unclosed literal people roster is deterministically normalized to:
  - `lifecycle_basis = MAINTAINED_SET_OR_STRUCTURE`
  - `knowledge_type = reviewable`
  - `valid_for_days = 365`
  - `lifecycle_proportional = true`
- An ineligible or unsupported roster remains `persist = false`; lifecycle
  normalization cannot bypass evidence gates.
- The same subject plus the exact same unordered member set refreshes the
  existing active claim instead of adding a wording-only duplicate.
- Refresh preserves the existing knowledge ID, canonical claim, curation,
  entity IDs, and relationship IDs while extending expiry and merging evidence.
- A changed member set cannot overwrite the existing roster. It remains a
  separate verified candidate for the normal curator/conflict path.
- Exact-ID updates now also preserve existing curation metadata.

## Scope

No SQLite schema change is required. Knowledge relationship contract version 2
and relationship support migration version 1 remain unchanged. UI, browser,
video playback, audio, and Companion Watch files are not modified.
