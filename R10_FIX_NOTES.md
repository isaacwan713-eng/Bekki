# Bekki R10 compact recommendation research

Build ID: `bekki-skills-v1-20260818-r10`

R10 keeps all R9 planning and grounding protections. It fixes the live case:

`给我推荐三个杯子`

R9 correctly recovered the category `cup`, but later stages still made the
simple request unnecessarily fragile. Broad brand discovery found unrelated
household brands, the brand and merchant models repeated whole search-result
objects instead of returning short decisions, one merchant JSON response hit
its output limit, and the remaining candidates were an unavailable niche cup
and a 100-count disposable pack. The honest result was zero cards.

R10 changes the research path:

- Ordinary recommendations search independent recommendation roundups,
  comparisons, and expert reviews before searching merchant pages.
- Brand and merchant models return source indexes only. Python keeps the source
  corpus, derives exact support excerpts, and reconstructs the selected domains.
- Every JSON call requests Ollama JSON mode; the two bounded index decisions use
  explicit JSON Schemas and much smaller output budgets.
- Brand evidence must mention the requested product category, preventing a
  generic household-brand list from turning Dove or Dyson into cup brands.
- Generic consumer recommendations reject explicit out-of-stock items and
  unrequested bulk/disposable listings. An explicit disposable or bulk request
  still permits them.
- Model failure still falls back to deterministic, visibly commerce-grounded
  merchant candidates and never invents a product.

External browser AI policy:

- Copilot or another browser AI may be an explicitly enabled discovery and
  summary assistant.
- Its output is never sufficient product evidence. Bekki must verify original
  public pages before reporting a brand, price, stock state, specification, or
  recommendation.
- Signed-in browser context is never enabled silently.

After installation, run `python main.py` and confirm:

`[BEKKI BUILD] bekki-skills-v1-20260818-r10`

Acceptance request:

`给我推荐三个杯子`

The log should proceed from a compact shopping plan to recommendation-first
discovery. Brand JSON should contain only names and source indexes; merchant
JSON should contain only source indexes. Live web evidence may still honestly
return fewer than three supported products or no results.
