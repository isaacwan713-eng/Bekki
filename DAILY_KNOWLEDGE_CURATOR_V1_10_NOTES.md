# Daily Knowledge Curator V1.10

Build: `bekki-daily-knowledge-curator-v1-10-20260828`

## Outcome

Bekki now separates knowledge approval from knowledge organization. The
existing `data/knowledge.json` remains the authoritative, auditable flat
ledger. Every verified stable or unexpired reviewable revision is also queued
in `data/knowledge/inbox.json` for a once-per-local-day idle-time curator.

The Gemma 4 curator—not Python—decides:

- which broad knowledge ecosystem owns a claim;
- whether an existing topic file should be reused;
- the primary and related entities and their relationship;
- claim facet, aliases, and retrieval keywords;
- whether a claim is distinct, duplicate, conflicting, or must be deferred.

A topic JSON represents one coherent ecosystem, not one entity. An
organization, its members, and related or sister organizations can share one
document while retaining different entity IDs. Python validates only the JSON
contract, safe opaque IDs, exact input coverage, lifecycle eligibility, and
atomic file writes. It contains no SNH48, member, sister-group, translation, or
other domain-specific classification table.

## Files

- `data/knowledge/inbox.json`: pending and completed curator queue records.
- `data/knowledge/topics/<topic_id>.json`: entities, relations, and claims.
- `data/knowledge/index.json`: topic alias and keyword lookup.
- `data/knowledge/conflicts.json`: quarantined contradictory claims.
- `data/knowledge/curator_runs.json`: daily success/failure audit.

Topic writes and index updates are atomic and keep a last-known-good `.bak`
copy. Invalid plans receive one AI recovery attempt. A second invalid plan or
runtime failure leaves the original inbox record pending.

## Mixed lifecycle answers

The External-AI lifecycle governors now explicitly identify requests that mix
reusable structure with current members, rosters, affiliations, schedules,
events, or news. The overall answer remains current-turn-only. A separate AI
partitions the answer into atomic claims and may policy-verify only the
low-impact stable/reviewable components. Current components are never written
to Knowledge. High-impact questions retain the existing second-certification
path and are not automatically persisted.

## Recall integrity

Topic documents improve retrieval with aliases, entity names, facets, and
keywords. The flat ledger remains authoritative for verification and expiry;
a stale topic copy cannot survive deletion, expiration, conflict quarantine,
or duplicate suppression in the ledger.

## Validation

- All modified Python sources compile.
- Root and Casper Knowledge mirrors are AST-identical.
- Full offline suite: 763 tests, OK; 9 opt-in/platform tests skipped.
- New tests cover broad ecosystem grouping, entity separation, keyword recall,
  current-fact exclusion, reviewable expiry, conflict quarantine, invalid-plan
  recovery, ledger authority, and mixed-answer partial persistence.
