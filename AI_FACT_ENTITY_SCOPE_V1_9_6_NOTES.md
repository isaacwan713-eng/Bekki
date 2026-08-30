# AI Fact Entity Scope V1.9.6

Build: `bekki-ai-fact-entity-scope-v1-9-6-20260828`

## Failure fixed

A translated FACT_LOOKUP query could collapse a meaningful entity
relationship. The browser would then search an adjacent organizational scope,
and every downstream AI could inherit that drift. Incomplete wrong-scope
evidence could also be mislabeled as `NOT_YET_AVAILABLE`, preventing the
governed External-AI fallback.

## AI-owned semantic handling

- An Entity Scope Planner AI derives the target entity, requested
  relationship, required facets, included scope, and adjacent excluded scopes
  from the original user message.
- An independent Query Scope Auditor AI reviews the generated browser query
  and every follow-up query. It may preserve source-language wording and
  rewrite a translation or hierarchy drift before any search runs.
- Search-summary, single-source, evidence-gap, resolver, and answer-writer
  prompts all receive the same binding Entity Scope.
- An independent Resolution Auditor AI must approve `FOUND` and
  `NOT_YET_AVAILABLE`. The latter requires positive non-availability evidence;
  missing pages, incomplete retrieval, and wrong-scope evidence fail closed as
  `INSUFFICIENT`.
- A rejected combined result cannot become an accepted direct reply, so the
  existing governed External-AI fallback remains reachable.

Python owns only schema validation, bounded execution, and fail-closed state
transitions. It has no special-case branch for SNH48, Chinese `分队`, `group`,
or any particular organization.

## Runtime diagnostics

Successful planning emits:

- `[CASPER FACT ENTITY SCOPE]`
- `[CASPER FACT QUERY SCOPE AUDIT]`
- `[CASPER FACT QUERY REWRITTEN]` when the audit changes the query
- `[CASPER FACT FOLLOW-UP QUERY REWRITTEN]` when a later query drifts

## Validation

- All Python sources compile.
- Root and Casper tool mirrors remain AST-identical.
- Mirrored FACT_LOOKUP prompts are byte-identical.
- Full suite: 751 tests, OK; 9 opt-in or platform-specific tests skipped.
- Live Ollama contracts now include entity-scope query correction and rejection
  of wrong-scope missing evidence as non-availability.
