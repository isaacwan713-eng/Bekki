# Bekki R19 lightweight runtime

Build ID: `bekki-skills-v1-20260818-r19`

R19 reduces routine model and browser load without moving semantic product
decisions into Python.

## What changed

- Melchior now returns `interaction_mode` (`TASK` or `COMPANION`) and a closed
  `context_profile`. Python validates those fields and uses them only to apply
  resource budgets.
- Ordinary questions, recommendations, research, tasks, and device actions skip
  Balthasar. Emotional support and relational conversation keep the full
  Balthasar plan.
- The per-turn Balthasar calibration generation was removed. Casper receives a
  fixed neutral calibration and the authoritative Melchior plan.
- Bekki no longer calls another model after every valid reply to summarize
  conversation state. Raw recent history and explicit memory remain available.
- Non-companion replies use a compact system prompt. Context is selected by
  Melchior and final generation is limited to 4K-8K context and 1.2K-2.4K output.
- Google is searched first. Bing is opened only if the primary results are
  missing or insufficient for the current evidence stage.
- Recommendation discovery reads at most four initial editorial pages and
  three recovery pages. Candidate verification uses smaller search/result and
  excerpt budgets.
- An Ollama runtime exception no longer triggers an immediate identical second
  recommendation-model request. JSON-format failures still receive one retry.

## Expected console behavior

For `给我推荐几个吸管杯`, the console should show a Melchior TASK plan followed
by `[BALTHASAR SKIPPED] RECOMMENDATION_RESEARCH`. If Google provides enough
usable results, no Bing fallback line should appear.

For `我今天很难受，陪我聊聊`, Melchior should return LOCAL_ANSWER with
`interaction_mode=COMPANION`, and Balthasar should run once.

After a normal generated reply, the console should show:

`[CONTEXT UPDATE SKIPPED] lightweight_runtime`

There should be no additional context-summary model generation.
