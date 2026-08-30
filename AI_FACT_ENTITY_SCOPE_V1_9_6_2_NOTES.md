# AI Fact Entity Scope V1.9.6.2

Build: `bekki-ai-fact-entity-scope-v1-9-6-2-20260828`

## Live failure found

All V1.9.6.1 live contracts passed, but the query certifier accepted the
literal phrase `SNH48 official sub-groups` by treating authority and freshness
words as if they disambiguated the entity hierarchy. The test proved only that
the AI returned `accepted=true`; it did not prove that the AI could detect the
known adjacent-scope interpretation.

## AI-owned adversarial correction

- The certifier must first paraphrase only the literal query, without borrowing
  hidden Entity Scope fields.
- It must construct the strongest interpretation targeting an excluded parent,
  affiliate, sibling, category, historical form, internal unit, or other
  adjacent scope.
- If a normal reader or search engine could plausibly follow that attack, the
  query is rejected regardless of the writer AI's approval.
- The writer receives the attack itself and must repair the relationship
  wording. The repaired literal is challenged again before search.
- The live contract separately submits the exact ambiguous literal observed in
  V1.9.6.1 and requires the adversarial AI to reject it before testing the full
  rewrite flow.

Python enforces only the structured AI verdict. It contains no SNH48, team,
translation, organization, or fixed phrase mapping.

## Validation

- All Python sources compile.
- Root and Casper prompts are byte-identical.
- Full suite: 753 tests, OK; 9 opt-in or platform-specific tests skipped.
