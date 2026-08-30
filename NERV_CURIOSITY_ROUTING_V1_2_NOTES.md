# NERV Curiosity Routing V1.2

Build: `bekki-nerv-curiosity-routing-v1-2-20260827`

## Fix

- A surprising public fact shared without an explicit verification request is
  `LOCAL_ANSWER`, not `CLAIM_CHECK`.
- `NERV_LEARNING` now has the same explicit-query boundary as the Curiosity
  Journal. It opens only for a direct request to list verified learned skills
  or reusable operations.
- A public sports fact can no longer expose the learned-skill inventory after
  a crossed-lane MAGI audit.
- The ordinary local reply is preserved so the post-turn Curiosity Writer can
  evaluate the actual fact instead of an unrelated inventory response.

## Validation

- The observed Ohtani sweeper crossed-lane trace is covered by regression.
- Explicit learned-skill inventory and Curiosity Journal queries still pass.
