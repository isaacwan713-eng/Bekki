# Bekki NERV Core V1

Build ID: `bekki-nerv-core-v1-3-20260825`

V1.3 completes the first live Profile read/write loop. An AI proposal that
labels a new stable key as UPDATE is reconciled by the store as its first ADD,
and the next request waits for the previous asynchronous profile write before
reading. The final writer now receives an explicit governed-profile contract:
the JSON `memory` output-field rule cannot suppress matching active NERV facts.
Runtime logs report both write status and final-context item count.

NERV is Bekki's governed long-term cognition layer. It surrounds the request
lifecycle but does not sit above MAGI semantically: the current user message
remains authoritative, MAGI retains SEARCH / LOCAL / COMMAND routing, and
Casper remains the only execution layer.

## V1 components

- `ProfileStore`: structured, versioned profile facts with evidence,
  confidence, status, history, and durable audit records.
- `ProfileWriter`: `gemma3:4b` decides semantic ADD / UPDATE / REMOVE / NONE
  proposals. Python validates only the closed schema, direct quote grounding,
  persistence policy, and lifecycle. The profile write runs after the result
  on a daemon worker so it does not delay delivery of the completed reply.
- `ContextSelector`: supplies bounded, least-privilege profile context.
  MAGI receives only normal location/device/constraint context; external AI
  receives none.
- `LearningEngine`: records request observations and explicit verified Casper
  skill outcomes. An ordinary successful reply never becomes a verified skill.
- `Governance`: atomic JSON generations, backup recovery, JSONL audit/events,
  confidence thresholds, sensitive-data review, and failure isolation.
  Learning events store a request digest instead of duplicating raw messages.

## Runtime data

NERV creates these files on first run under the preserved `data` directory:

- `data/nerv/profile.json`
- `data/nerv/skills.json`
- `data/nerv/learning_events.jsonl`
- `data/nerv/audit.jsonl`

Sensitive or below-0.80 profile proposals are retained as `pending_review`
and are not exposed as active context. Pending updates never replace the last
active value. Explicit forget requests mark the matching item removed while
retaining audit history.

The legacy memory store remains readable during V1 compatibility, but new
long-term profile writes use NERV. Legacy temporary memory remains enabled.
Casper's existing skill registry keeps ownership of candidate execution,
machine receipts, user confirmation, invalidation, and reuse.

## Validation

- 17 focused NERV tests cover grounding, sensitivity, conflicts, removal,
  audience isolation, writer boundaries, lifecycle, and integration.
- Full suite: 589 tests passed; 4 platform-dependent tests skipped.
- Stable UI source files are unchanged from V1.3.9.5.
