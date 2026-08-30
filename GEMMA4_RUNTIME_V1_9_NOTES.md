# Bekki AI Fact Entity Scope V1.9.6.2

Build: `bekki-ai-fact-entity-scope-v1-9-6-2-20260828`

V1.9.1 adds a deterministic guard for obvious documentation-query
placeholders before AI semantic review. It also makes the Gemma 4 review prompt
judge the literal query instead of borrowing missing words from plan fields.

V1.9.2 fails closed when FACT_LOOKUP has no accepted evidence, binds temporal
scope through a strict schema, and constrains Curiosity candidate IDs to the
exact current enumeration.

V1.9.3 locks `allow_previous_period` to false for CURRENT_ACTIVE_STATE after
model output, preventing older facts from satisfying a current-state request.

V1.9.4 requires primary and independent fact validators to confirm directness,
completeness, source support, and no unsupported additions. Accepted fact text
is returned directly and cannot be expanded by the final persona model.

V1.9.5 adds a governed External-AI fallback after bounded 3-5-7 research is
exhausted. Bekki separates permanent stable knowledge, periodically reviewable
knowledge, current-turn-only facts, and high-impact facts. Stable and
reviewable low-impact answers may enter Knowledge; reviewable items receive an
AI-selected expiry. Current person affiliation or status is answered without
persistence. High-impact questions require a second External-AI certification
and are never automatically stored.

V1.9.5.1 fixes the changing-fact contract: current-turn-only facts require no
expiry because they are never stored. A NORMAL-risk public SKIP now receives
one AI recovery pass so contradictory decision fields cannot suppress a valid
current affiliation lookup.

V1.9.6 makes entity scope an AI-owned contract. One AI derives the exact
entity hierarchy, relationship, and requested facets from the original user
message. A separate AI audits and, when needed, rewrites the initial and
follow-up browser queries. A final independent AI rejects combined-evidence
outcomes that drift to a parent, affiliate, sibling, category, internal unit,
or other adjacent entity. It also prevents incomplete search evidence from
being mislabeled as proof that a fact is not yet available. Python validates
only structured contracts and contains no domain-specific keyword routing for
this decision.

V1.9.6.1 adds two independent semantic audits. A query certifier judges the
literal search text without relying on hidden scope fields and sends ambiguous
translation or hierarchy wording back for one AI repair. A lifecycle auditor
independently reclassifies External-AI answers and selects reviewable Knowledge
intervals according to plausible change rate and stale-answer cost. Python
does not contain entity keywords or a fixed recheck-day table for either
decision.

V1.9.6.2 changes query certification from approval-oriented review to an
adversarial ambiguity challenge. The AI must paraphrase only the literal query,
construct the strongest adjacent-entity interpretation, and decide whether a
normal reader or search engine could follow it. Authority or freshness alone
cannot establish an entity hierarchy. A plausible attack forces one AI repair
and a second challenge. This remains semantic model judgment; Python contains
no organization, language, or team-name mapping.

## Model topology

- `gemma4:12b`: primary conversation, reliable MAGI, research, vision,
  learning, NERV verification, recovery, and final writing.
- `gemma4:e4b`: fast Melchior routing, profile writing, objective-fact audit,
  and bounded launcher vision.
- `llama3.2:latest`: small closed auxiliary decisions only.

No active Python runtime path requests Gemma 3 or `gpt-oss:20b`. Existing old
weights may remain in Ollama for rollback without being loaded by Bekki.

## Compatibility boundary

Gemma 4 supports a native system role and Boolean thinking toggle. V1.9:

- passes reusable prompt instructions in Ollama's `system` field;
- sends the current request separately in `prompt`;
- maps legacy `low` to thinking disabled so quick and JSON calls do not become
  unexpectedly slow or exhaust their output budgets;
- enables thinking only for explicit `True`, `high`, or `on`;
- keeps schema-constrained JSON in Ollama's `format` field;
- continues reading final output from `response` while Ollama's separate
  `thinking` field remains diagnostic only.

## RTX 5080 16GB envelope

- Gemma 4 12B context remains capped at 8192 tokens.
- Gemma 4 E4B context remains capped at 4096 tokens.
- Recoverable CUDA/HTTP 500 failures still unload and retry once at 4096/1024.
- Models above 12B are remapped to 12B; 26B and 31B are not runtime options.
- Only one Ollama model is retained across a switch.

## Required downloads

```powershell
ollama pull gemma4:12b
ollama pull gemma4:e4b
ollama pull llama3.2:latest
```

Gemma 4's official training-data cutoff is January 2025. Objective Fact
Verification V1.8 therefore remains active for current and uncertain public
facts; upgrading the base model does not turn it into a factual database.

## Rollback

The installer keeps a timestamped copy of the previous source runtime. Ollama
model files live outside the project and are not deleted, so the previous Gemma
3 build can be restored without downloading its weights again.

## Validation

- All Python sources compile successfully.
- Root and compatibility mirrors remain AST-identical.
- Complete suite: 751 tests, OK; 9 opt-in or platform-specific tests skipped.
- Live Gemma 4 generation must be run on the target Windows/Ollama machine
  after downloading the new weights.
