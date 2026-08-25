# Bekki R22 AI-owned market localization

Build ID: `bekki-skills-v1-20260818-r22`

R22 is a focused correction to R21's successful summary-audit architecture.
The R21 auditor correctly rejected toddler products, but the initial search AI
used the literal US query `straw cup`, which commonly retrieves toddler
training cups.

## AI-owned localization

- Python contains no Chinese-to-English product mapping table.
- The 12B planning AI receives the original wording, US runtime profile, and
  explicit or unspecified audience.
- The AI chooses natural US commercial terminology. For example, a general
  request for 吸管杯 can be searched as `tumbler with straw`, while an explicit
  toddler request can remain `toddler straw cup`.
- Localization may change search wording but may not invent material,
  insulation, capacity, beverage, use-case, brand, price, or popularity
  requirements.

## Recovery isolation

- Failed first-pass sources remain available only for discovery deduplication.
- The recovery candidate AI receives only sources returned by its new queries,
  preventing old toddler-heavy snippets from dominating again.
- Python enforces only an exact-title retry boundary; already rejected titles
  cannot be returned unchanged. Semantic category and fit decisions remain AI-
  owned.
- R21's adversarial verification and one-page evidence escalation remain
  unchanged.
