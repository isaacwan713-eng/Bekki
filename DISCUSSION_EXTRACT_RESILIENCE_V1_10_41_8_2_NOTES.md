# Discussion Extract Resilience V1.10.41.8.2

- Keeps the existing `DISCUSSION_FEED` route for mixed/open requests such as
  `卡黄是闹翻了吗，她们为什么会闹翻？`; it does not fall back to
  `CLAIM_CHECK`, `SOCIAL_RESEARCH`, or 3→5→7.
- Extracts at most two selected discussion sources per local-model request,
  instead of requesting one large six-source JSON array.
- Adds structural recovery for truncated discussion JSON. Every fully closed
  item before the malformed tail remains available; no missing text or field
  is invented to repair the incomplete item.
- Retries only missing source indices, one at a time, with a compact evidence
  packet. If one retry still fails, that source is omitted while successful
  batches continue into synthesis and cards.
- Bounds each extracted source to one concise attributed summary, at most three
  claims, one short uncertainty statement, and an optional bounded quotation.
- Instructs synthesis to name the people behind a pairing nickname once when
  readable sources explicitly and consistently identify them; conflicting or
  absent identities are not inferred.
- Prevents NERV Curiosity from describing a two-character fandom pairing as
  “two words,” splitting its characters, or asking for identities already
  stated in an evidence-grounded response.
- Includes Xiaohongshu Evidence Hotfix V1.10.41.8.1 and Discussion Feed
  V1.10.41.8.
