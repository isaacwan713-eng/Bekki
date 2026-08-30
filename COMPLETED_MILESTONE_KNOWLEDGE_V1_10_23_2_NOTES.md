# Bekki Completed Historical Milestone Knowledge V1.10.23.2

Build ID: `bekki-completed-milestone-knowledge-v1-10-23-2-20260830`

This release corrects the TWICE debut-year Knowledge intake failure without
adding an AI role, automatic retry, or synchronous answer gate.

- A request to discover when or in which year an already completed named
  milestone occurred is `EXPLICIT_PERIOD`, even when the user does not yet know
  the date.
- Public debut, founding, first release, first appointment, and similar
  one-time milestones are completed history rather than current state.
- The accepted, source-supported exact period remains attached to the atomic
  claim and may enter Knowledge as `FIXED_HISTORY` with stable lifecycle.
- Retrieval `CURRENT_ACTIVE_STATE` metadata controls evidence freshness only;
  it cannot override a visibly completed historical claim.
- Current rosters, affiliations, schedules, prices, versions, news, and live
  events remain current-turn-only.
