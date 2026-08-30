# Bekki Objective Fact Verification V1.8

Build: `bekki-objective-fact-verification-v1-8-20260827`

## Problem fixed

A `LOCAL_ANSWER` could invent concrete public facts when verified Knowledge was
empty. The draft was shown immediately, while NERV Curiosity ran only after the
turn. Curiosity could then copy false names from that draft into an External AI
question, amplifying the original error.

The observed SNH48 failure is the regression fixture: the local draft invented
M and L teams even though those names were not grounded by the user or verified
Knowledge.

## New pre-display boundary

- Only ungrounded `LOCAL_ANSWER` drafts enter the new boundary.
- A deterministic prefilter detects likely public objective specifics without
  adding model latency to ordinary local turns.
- A compact semantic auditor chooses `ALLOW` or `VERIFY`.
- `VERIFY` reroutes the original request through Casper `FACT_LOOKUP` with
  `official_first` source policy before any draft text reaches the UI.
- Invalid or failed audits fail closed to `VERIFY`.
- A rerouted lookup without an audited answer fails closed and does not expose
  the original local draft.
- User disagreement is a trigger to investigate, not evidence that the user's
  alternative claim is correct.

## Authority boundary

Public objective facts are independently verified. Facts about the user,
family, devices, routines, and preferences remain user-authoritative and do not
go to public web verification. Greetings, creative writing, translation,
summarization of supplied text, and pure math retain the fast local path.

Changing facts such as current rosters are not automatically promoted into
stable long-term Knowledge. They are looked up again when needed.

## Curiosity isolation

For `LOCAL_ANSWER`, Curiosity receives an empty `bekki_reply` plus
`assistant_grounding=UNVERIFIED_ASSISTANT_OUTPUT`. It can use the user's public
topic, but cannot recover or introduce names, teams, people, dates, or versions
that appeared only in Bekki's draft. Research modes carry
`EXTERNAL_EVIDENCE_AVAILABLE` and may pass their grounded reply.

## Observable logs

```text
[NERV OBJECTIVE FACT AUDIT] decision=VERIFY reason=...
[NERV OBJECTIVE FACT REROUTE] LOCAL_ANSWER -> FACT_LOOKUP
[CASPER RESULT] FACT_LOOKUP completed evidence=...
```

If evidence is unavailable:

```text
[NERV OBJECTIVE FACT BLOCKED] status=...
```

## Validation

The focused regression suite contains 159 tests, including SNH48 false-list,
public death-status, user challenge, personal-authority, fast-local bypass,
audit fail-closed, official-first reroute, evidence acceptance, and Curiosity
reply-isolation contracts.
