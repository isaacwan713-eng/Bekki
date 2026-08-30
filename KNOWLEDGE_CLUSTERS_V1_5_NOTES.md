# Knowledge Clusters V1.5

Build: `bekki-knowledge-clusters-v1-5-20260827`

## Curiosity and Knowledge are separate

Curiosity may investigate either a stable background gap or a useful current
snapshot. A current roster, trade, injury, price, schedule, policy, software
version, event, or news item may help the current conversation, but it can never
be promoted into long-term Knowledge.

Only stable, reusable public facts are eligible for persistence. This boundary
is enforced in Python even if an AI labels a changing fact incorrectly.

## Tiered certification

- `standard`: for ordinary stable background, organization, culture, history,
  and sports facts. The external-AI answer is a corroborating signal and one
  qualified readable independent source is required.
- `double`: for medical, legal, and sufficiently technical or high-consequence
  claims. The external-AI answer is only a hypothesis. Promotion requires two
  independent qualified sources, consensus, and a separate second
  certification pass.

The AI selects the semantic tier and knowledge domain. Python prevents medical
or legal claims from being downgraded from `double` and prevents every
non-stable claim from entering Knowledge.

## Clusters and fast recall

Verified entries are grouped by knowledge domain and reusable entity or concept
in `data/knowledge_clusters.json`. Retrieval indexes the subject, claim, topics,
domain, cluster entity, and cluster topics.

Before a normal non-action response, Bekki performs deterministic local
retrieval. Matching verified cluster facts are supplied to the final local
answer without an extra model-routing call, external-AI request, or web search.
For example, verified SNH48 organizational knowledge can support a later
question about improving a company modeled on SNH48.

## Verification budgets

Standard curiosity verification uses the first three-source search budget and
may accept one qualified extracted source. Double verification retains the
progressive 3/5/7/10 evidence search and stricter consensus gate.

## Safety behavior

Insufficient, conflicting, non-stable, high-risk, or malformed claims remain
outside Knowledge. Existing legacy changing entries are excluded from active
retrieval and cluster rebuilding.
