# Bekki R21 summary-first research

Build ID: `bekki-skills-v1-20260818-r21`

R21 keeps R20's US-oriented Google-primary/Bing-fallback runtime profile while
reducing browser and model load during recommendation and ordinary fact
research.

## Recommendation flow

- Google AI Overview and search-result snippets create the initial candidate
  set. Independent review snippets remain visible to the candidate model.
- A separate adversarial 12B audit checks category, audience, and every
  user-explicit criterion. It must identify contradictions and missing support.
- `GENERAL_UNSPECIFIED` means ordinary general/adult everyday use. A product
  explicitly limited to babies, toddlers, children, or another niche fails the
  audience check.
- Pages are not opened by default. If the auditor returns `NEEDS_PAGE`, Casper
  opens at most one non-merchant evidence page for that candidate and audits it
  once more.
- Price, stock, sellers, checkout, and purchase links remain outside the
  recommendation route.

## Ordinary fact flow

- A first 12B AI proposes an answer from Google AI Overview and indexed search
  snippets.
- A second independent 12B AI looks for hallucinations, stale time periods,
  source disagreement, contradictions, and errors copied from the overview.
- The fast answer is accepted only when two distinct sources support it and all
  four structural checks pass. Otherwise Casper falls back to the existing
  original-page research path.
- High-risk fact requests bypass the fast path and keep strict page reading.

## Test focus

- AI Overview extraction in English and Chinese.
- Zero page reads on the normal recommendation fast path.
- One-page maximum on recommendation evidence escalation.
- Audience contradictions cannot pass even when the first AI recommends them.
- Search-summary fact answers require a separate correcting audit and two
  sources.
