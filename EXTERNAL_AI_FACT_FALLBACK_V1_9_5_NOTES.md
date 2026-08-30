# External AI Fact Fallback V1.9.5.1

Build: `bekki-external-ai-fact-fallback-v1-9-5-1-20260828`

When bounded FACT_LOOKUP research cannot produce one complete answer, Bekki
may ask ChatGPT Desktop with only the current public question. A local Gemma 4
policy pass selects the lifecycle before anything is sent.

## Lifecycles

- `stable`: durable science or history. The answer is scope-audited, marked
  verified, and stored without expiry.
- `reviewable`: useful structure that can change occasionally, such as an
  organization's official teams or a complete body of amendments. The answer
  is scope-audited, stored, and removed from active recall at its AI-selected
  recheck date.
- `changing`, `event`, or `news`: current person affiliation, roster, schedule,
  version, or one-time event. The External-AI answer is returned for the
  current turn without certification and is never stored.
- `HIGH` importance: contract, legal, medical, financial, safety, death/status,
  reputation, and similarly consequential questions require a second
  External-AI certification. They are not automatically stored.

Credentials, authentication data, and private/sensitive requests never enter
the automatic External-AI fallback.

The accepted External-AI answer becomes the immutable direct reply. The final
persona model cannot add teams, members, dates, clauses, or other unsupported
details afterward.

## Validation

- 745 deterministic tests pass.
- 7 live Ollama tests are opt-in and skipped by the deterministic suite.
- Root and Casper compatibility mirrors remain AST-identical.
