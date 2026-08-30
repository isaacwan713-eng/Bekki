# NERV Curiosity Selection V1.1

Build: `bekki-nerv-curiosity-selection-v1-1-20260827`

## Selection boundary

- Public figures, athletes, teams, leagues, companies, products, public
  events, and published statistics are eligible public knowledge.
- Sports and other specialist domains do not need to be generalized into
  anonymous or fundamental science questions.
- When related drafts exist, the selector chooses the strongest useful one
  instead of rejecting the entire theme.
- The privacy boundary continues to reject user-private, non-public personal,
  credential, account, proprietary, private-file, and device information.

## Recovery and queue state

- Any initial `SKIP` or invalid candidate ID receives one independent AI
  recovery review.
- A confirmed `SKIP` must identify one exact candidate, which is moved to
  `DISMISSED` so it cannot be selected forever.
- Python validates exact opaque IDs but does not make the semantic selection.

## Validation

- The observed Ohtani sweeper/public-athlete false rejection is covered as a
  recovery regression.
- Core routing, NERV, External AI Desktop, screenshot search, and UI tests:
  115/115 passed.
