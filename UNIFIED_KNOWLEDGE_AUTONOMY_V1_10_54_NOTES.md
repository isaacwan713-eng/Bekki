# Unified Knowledge Autonomy V1.10.54

Build: `bekki-unified-knowledge-autonomy-v1-10-54-20260905`

## What is unified

- The earlier profile-guided background learner (for interests such as
  Manchester United), verified Curiosity intake, Knowledge curation, L1-L5
  layering, relationship projection, taxonomy, and Topic Lifecycle now feed one
  Knowledge pipeline.
- Bekki's desktop idle timer and the existing Windows Task Scheduler invoke the
  exact same `knowledge_worker.run_autonomy_cycle` executor.
- A project-scoped cross-process lock rejects a second simultaneous trigger
  instead of allowing duplicate research or duplicate writes.

## Topic priority

Each autonomous run selects at most one lifecycle-owned Topic:

1. a due reviewable/paused Topic refresh;
2. an ACTIVE Topic with a concrete `next_focus`;
3. the bounded profile-guided fallback when its 30-day interval is due.

Urgency is ranked before `interest_score`; interest ranks Topics inside the
same urgency class. An unresolved Curiosity question temporarily owns its
Topic, so the background learner cannot open a parallel branch. An ordinary
`PAUSED_COMPLETE` Topic remains paused until its refresh is due. Due refreshes
have a 24-hour retry cooldown and open gaps have a 7-day cooldown.

## Persistence boundary

- Stable fixed history and durable explanations can enter long-term Knowledge.
- Reusable maintained sets/structures can enter as `reviewable` with an expiry.
- Match results, schedules, daily standings, headlines, rumors, and other
  event/news/transient findings remain only in `learning_logs.json`, whose
  authoritative copy is in SQLite.
- Every reusable autonomous record still enters the same curator inbox before
  it can become a fully browsable Topic claim.

## Runtime behavior

The first desktop autonomy check occurs after five idle minutes and repeats
every ten minutes as a cheap local due check. It never begins during a user
request, Companion Watch session, Curiosity run, Knowledge curation, or stable
review. The Windows task continues to check daily; its `--interval-days`
setting controls only the profile fallback, while an actually due lifecycle
refresh can run sooner.

Use this read-only command to inspect the current plan without starting web
research:

```powershell
python knowledge_scheduler.py plan
```

To run one bounded cycle intentionally:

```powershell
python knowledge_scheduler.py run --force
```

## Validation

Close Bekki, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\TEST_UNIFIED_KNOWLEDGE_AUTONOMY_V1_10_54.ps1
```

The validator checks build/runtime wiring, the one-topic contract, SQLite
integrity and hashes, learning-log shape, lifecycle-compatible selections, and
that no event/news/transient record became active Knowledge.

## Unchanged scope

Bilibili navigation, UP profile rendering, playback, video resolution, UI
fonts, and Companion Watch output are unchanged. Companion Watch only gains an
idle-resource guard so autonomous learning cannot start during a watch session.
