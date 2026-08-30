# AI Fact Entity Scope V1.9.6.1

Build: `bekki-ai-fact-entity-scope-v1-9-6-1-20260828`

## Failure fixed

The V1.9.6 Entity Scope contract could correctly exclude an adjacent entity
while still approving a translated literal query whose wording remained
ambiguous to the search engine. Separately, the first External Fact Governor
could choose the schema maximum of 3650 days for reusable facts that should be
checked more often.

## AI-owned correction

- An independent Query Certifier receives the original message, binding Entity
  Scope, and only the literal candidate query. It rejects wording that depends
  on hidden exclusions or leaves the entity hierarchy ambiguous.
- A rejected query receives one AI rewrite with the independent failure as
  feedback, then must pass certification again before browser discovery.
- An independent Lifecycle and Freshness Auditor re-reads each public fact
  request after the first governor. It owns impact, sharing, persistence class,
  and any review interval.
- Review intervals are selected semantically from likely change rate and the
  cost of stale recall. The 3650-day schema ceiling is only an envelope, not a
  default.
- Python validates schemas and fail-closed transitions only. It has no SNH48,
  translated team-word, organization, or fixed review-day decision table.

## Validation

- All Python sources compile.
- Root and Casper prompt mirrors are byte-identical.
- Full suite: 753 tests, OK; 9 opt-in or platform-specific tests skipped.
- Live contracts now require an independently certified literal query and a
  reviewable interval shorter than the schema maximum for the structural test
  case.
