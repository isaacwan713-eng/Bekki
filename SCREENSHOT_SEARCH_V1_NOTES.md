# Bekki Screenshot Search V1

Build: `bekki-screenshot-search-v1-1-20260827`

## What changed

- One local Vision pass now runs before MAGI and Melchior when an image is
  explicitly attached.
- The route can use grounded visible text, product identifiers, sports
  entities, headlines, claims, dates, scores, and error codes.
- Image explanation remains `LOCAL_ANSWER`.
- Requested web lookup, sports/news claim verification, and exact-product
  shopping reuse Casper's existing `FACT_LOOKUP`, `CLAIM_CHECK`, `NEWS_FEED`,
  and `SHOPPING_RESEARCH` pipelines.
- Ambiguous visual identity is routed to clarification rather than broad search.
- Visual fact checks anchor the candidate claim before Casper runs. Exact teams,
  scores, and a local calendar date resolved from visible relative-time text are
  preserved; a query that drops numeric/date anchors is recovered automatically.

## Privacy boundary

- Screenshot bytes are sent only to the configured local Ollama Vision model.
- Casper receives bounded text evidence, never the image.
- Common email, phone, SSN, payment-number, password, and verification-code
  patterns are removed before visual evidence enters a web-search request.
- V1 does not use Google Lens or any reverse-image upload service.

## Validation

- Screenshot Search tests cover sports claim routing, product identity handoff,
  local explanation, ambiguity, single-pass ordering, and privacy redaction.
- Core routing/runtime regression: 103/103 passed.
