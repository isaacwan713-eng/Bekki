# Bekki R9 generic shopping-plan recovery

Build ID: `bekki-skills-v1-20260818-r9`

R9 keeps every R8 grounding, evidence, context-isolation, GPU, and
no-fabrication protection. It fixes the live failure reproduced by:

`给我推荐三个杯子`

The compact planner produced the correct English category but invalid source
ownership (`cup` instead of the exact Chinese source phrase `杯子`). Its retry
then emitted the schema placeholder `normalized category` as a literal value.
R8 rejected both plans before web search, but its deterministic recovery was
limited to requests with explicit popularity intent, so the result contained
zero cards.

R9 changes that boundary without relaxing it:

- Category-consensus recovery now covers ordinary product recommendations as
  well as viral, mainstream, and popular-brand requests.
- Both compact attempts must still agree on the cleaned English category.
- The separate compact semantic verifier must still bind that category to an
  exact phrase in the authoritative current or permitted referential source.
- Missing constraints, conflicting categories, invented modifiers, stale
  context, bad units, and bad budgets still fail closed.
- A recovered ordinary request uses a deterministic evidence-oriented query,
  such as `cup best rated high review count United States`; it does not choose
  or hardcode any brand.
- The planner prompts now explicitly demonstrate that an English search
  category must keep `source_phrase` in the user's original language and that
  schema descriptions must never be emitted as literal values.

After installation, run `python main.py` and confirm:

`[BEKKI BUILD] bekki-skills-v1-20260818-r9`

Acceptance request:

`给我推荐三个杯子`

The log should either accept a valid compact plan or show
`[SHOPPING PLAN REPAIR] grounded category consensus`, then continue to search
instead of ending immediately with zero cards. Live evidence may still
honestly return fewer than three supported products or no results.
