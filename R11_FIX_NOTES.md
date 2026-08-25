# Bekki R11 router JSON compatibility repair

Build ID: `bekki-skills-v1-20260818-r11`

R11 keeps the R10 recommendation-first shopping flow and compact brand and
merchant index schemas. It fixes a regression reproduced immediately after
R10 installation by:

`给我推荐三个杯子`

The request never reached Shopping. R10 coupled `expect_json=True` to Ollama's
`format=json` for every JSON-producing prompt. On the installed gpt-oss router,
the primary call returned an empty response and the recovery call returned
prose, so Melchior rejected both and the worker stopped.

R11 separates two responsibilities:

- `expect_json=True` parses and validates a model's JSON response but does not
  silently change the Ollama generation format.
- `json_schema=...` explicitly enables Ollama structured output only for the
  compact shopping brand-index and merchant-index decisions that need it.
- Melchior, Balthasar, context, and other established JSON prompts retain their
  pre-R10 model invocation behavior.
- The R10 fixes remain active: recommendation-first discovery, product-category
  evidence binding, short index-only shopping JSON, and rejection of explicit
  out-of-stock or unrequested bulk/disposable products.

After installation, run `python main.py` and confirm:

`[BEKKI BUILD] bekki-skills-v1-20260818-r11`

Acceptance request:

`给我推荐三个杯子`

The log must show a valid `[MELCHIOR PLAN]` and continue into
`[SHOPPING PLAN CONTEXT]`; it must not stop with `Melchior could not produce a
valid routing mode after retry.`
