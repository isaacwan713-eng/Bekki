# Bekki R14 compound product category translation repair

Build ID: `bekki-skills-v1-20260818-r14`

R14 fixes the R13 failure reproduced by:

`给我推荐几个吸管杯`

The router correctly chose product recommendation, but both general planners
reduced the compound Chinese category to generic `cup`. The semantic guard
correctly rejected that weakened plan, leaving zero cards before search.

R14 adds a general, bounded category recovery:

- After both full plans fail, a compact structured-output step copies the exact
  authoritative category phrase and translates the complete product kind.
- It does not choose a brand, merchant, quantity, popularity, or preference.
- A separate semantic verifier must confirm the translation and all explicit
  constraints before Python builds the regional query.
- The mechanism covers compound categories generally, such as straw cups,
  training cups, insulated lunch boxes, and noise-cancelling headphones; it is
  not a cup-specific lookup table.
- Editorial source validation now requires every meaningful compound-category
  token. A generic cup article cannot support a straw-cup recommendation.
- Missing size, material, budget, use-case, or other explicit constraints still
  fail closed.

The R12 recommendation-versus-shopping split and the R13 hybrid recommendation
count rule remain unchanged.
