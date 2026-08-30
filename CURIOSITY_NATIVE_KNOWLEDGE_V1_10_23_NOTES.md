# Bekki Curiosity Native Knowledge and Idle Exploration V1.10.23

Build ID: `bekki-curiosity-native-knowledge-v1-10-23-20260830`

This release completes the Curiosity-to-Knowledge loop without adding an AI
role or a synchronous gate.

- A successfully verified Curiosity Knowledge item is supplied to the existing
  Writer as `VERIFIED_KNOWLEDGE_IDLE`. Bekki may draft a proportionate next
  question while idle instead of waiting for another user turn.
- Every continuation records its source Curiosity ID and Knowledge ID.
  Unverified answers, local-model guesses, and transient current states cannot
  seed a continuation.
- The existing breadth ladder still begins with recognizable people, works,
  performances, events, stories, relationships, culture, or ordinary behavior
  before specialist operations or business analysis.
- The Curiosity daily limit migrates from the legacy default of 3 to 10 for
  this test cycle. Failed attempts and completed questions both consume one
  local-day slot.
- Curiosity Knowledge can retain durable explanations, reviewable maintained
  structures, and exact fixed historical snapshots. Current people rosters,
  affiliations, schedules, events, and news stay in the journal only.
- Newly admitted Curiosity Knowledge can reopen Daily Curator later on the same
  day. An expired reviewable duplicate is refreshed only after fresh verified
  evidence.
- Daily Curator stores a presentation-only preferred claim for established
  native names. Chinese public names normally use Chinese, Japanese public
  names use Japanese, source or romanized spelling stays as an alias, and
  uncertain conversions remain unchanged.
- The flat Knowledge claim remains factual authority. Native display cannot
  change facts, entity identity, dates, membership, or temporal scope.
