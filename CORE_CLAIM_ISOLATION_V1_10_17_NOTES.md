# Core Claim Isolation V1.10.17

Build: `bekki-core-claim-isolation-v1-10-17-20260829`

## Corrected failure

V1.10.16 could successfully carry a canonical core answer through the UI and
Knowledge path, but Gemma could still reject that core after seeing one false
adjacent event. It treated the entire candidate as globally unreliable and
used latent familiarity such as “not standard” or “not verifiable” as negative
evidence even when bounded web evidence did not contradict the core.

## Existing auditor boundary

The same Answer Auditor now performs an extractive scope, policy, and conflict
audit:

- The selected External-AI answer is the permitted primary authority for an
  eligible low-impact stable or reviewable fallback.
- Model memory, training cutoff, intuition, and familiarity are not evidence.
- Missing web corroboration is expected after bounded research and is not a
  contradiction.
- Candidate assertions are separated into required core, necessary
  qualification, and removable addition.
- A false adjacent event or source claim does not contradict the core it tried
  to justify unless it directly asserts the opposite of that core.
- Only a direct retained-core contradiction or supplied bounded web conflict
  evidence may establish a negative factual conflict.

When deletion alone leaves every requested facet completely answered, the
auditor must use `AUTO_VERIFY` with `USE_CANONICAL_CORE`. Incomplete,
high-impact uncertified, scope-shifted, or directly contradicted cores still
fail closed.

No new AI role, gate, arbiter, external request, domain-specific classifier,
or model call was added. Python still validates only the audit contract shape
and routes the AI-selected answer.
