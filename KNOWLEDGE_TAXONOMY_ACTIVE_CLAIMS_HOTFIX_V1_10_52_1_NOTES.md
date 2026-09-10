# Knowledge Taxonomy Active Claims Hotfix V1.10.52.1

Build: `bekki-knowledge-taxonomy-active-claims-hotfix-v1-10-52-1-20260905`

## Why the V1.10.52 live check could fail

Topic documents retain old claim copies as audit history. Bekki's runtime and
Topic Lifecycle assessor already intersect those copies with the authoritative
active Knowledge ledger. The first V1.10.52 validator instead checked every
topic-local record whose copied status was still `verified`.

That could report an old duplicate or superseded claim as unclassified even
though the current replacement was correctly classified. It could also inflate
the category index's claim and layer counts.

## Fix

- The taxonomy index now counts only claim IDs that remain active in the flat
  authoritative Knowledge ledger.
- Startup detects an older taxonomy index and rebuilds that index once; it does
  not rerun semantic classification.
- Stable claims must still be verified and not duplicate/conflict records.
- Reviewable claims must additionally have a valid future expiry.
- The live validator applies the same rules and prints ignored topic claim
  copies separately for audit visibility.
- A retained old copy is not deleted or rewritten.

The existing topic category paths, fact types, L1-L5 layers, source evidence,
relationships, temporal scopes, and lifecycle states remain unchanged.

## Scope

No Bilibili navigation, search, playback, browser-profile, UI, or Companion
Watch behavior changes in this hotfix.

## Validation

Run the same read-only validator after installation:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_TAXONOMY_V1_10_52.ps1
```

An old topic copy may appear under `ignored_topic_claim_copies`; that is
expected and does not fail the test. Only an unclassified authoritative active
claim is a failure.
