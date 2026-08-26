# Bekki NERV Knowledge Verification V1.4

Build ID: `bekki-nerv-knowledge-verification-v1-4-20260826`

V1.1 narrows Curiosity Journal retrieval to explicit user requests, accepts
English-only internal trigger metadata when the Chinese outbound question and
reason are correct, and makes three privacy-screened questions the daily
default.

V1.2 makes the outbound question the authoritative language boundary. If a
small model produces an English or factually noisy internal reason for a valid
Chinese question, NERV replaces that visible reason with a bounded Chinese
explanation instead of discarding the question.

V1.3 anchors CJK claims directly in the search query instead of asking a model
to translate named entities. It also removes free-form candidate/search reasons
and the external answer from the final verdict packet, so an erroneous English
label such as `koala` cannot override the original `袋熊` claim.

V1.4 closes the next live-test gap: the candidate must directly answer the
original question. Why/cause/mechanism questions require a causal or
mechanistic claim. If the first extraction selects an incidental detail such as
`袋熊的肛门呈圆形`, NERV performs one bounded recovery pass for the core answer;
if recovery still drifts, the candidate is skipped. Non-temporal explanatory
biology, anatomy, physics, and mechanism questions are normalized to stable
knowledge with `valid_for_days=null`.

## Purpose

ChatGPT remains an external adviser, not Bekki's reasoning authority. A
Curiosity answer is stored as `ANSWERED_UNVERIFIED` and treated only as a
hypothesis.

## Verification loop

1. NERV extracts at most one public, low-risk, durable factual candidate.
2. Bekki builds a separate claim-check query and runs its existing 3→5→7
   evidence search.
3. Python requires consensus, at least two votes, and at least two readable
   independent domains with source scores of 70 or above.
4. A local verifier compares the candidate with extracted web evidence. It may
   `PROMOTE`, `KEEP_UNVERIFIED`, or `REJECT`.
5. Knowledge persistence independently rechecks the evidence boundary. Only a
   low-risk stable/changing claim with confidence at least 0.85 is saved.

The Knowledge entry stores the evidence-supported canonical claim and all
qualified sources. Its provenance records `external_ai_role=hypothesis_only`;
the ChatGPT answer is never treated as evidence.

## Fail-closed behavior

- One readable source is insufficient.
- Duplicate domains do not count as independent evidence.
- Failed pages and sources scored below 70 do not count.
- High-risk, event, news, personal, private, instruction-like, ambiguous, or
  conflicting content does not enter long-term Knowledge.
- Search failure leaves the Curiosity item unverified and never invents a
  verified claim.

## Live test

After a clean Curiosity draft is answered by ChatGPT Desktop, expect:

```text
[NERV KNOWLEDGE CANDIDATE] status=VERIFY claim='...'
[NERV KNOWLEDGE CANDIDATE RECOVERY] causal_answer_required
[NERV ENTITY-ANCHORED QUERY] '...'
[NERV KNOWLEDGE VERIFICATION] decision=PROMOTE outcome=VERIFIED knowledge=verified sources=2
```

Then ask `Bekki 最近在好奇什么？`. The Journal should show the canonical
verified knowledge and independent source domains. A claim with insufficient
evidence should instead show `独立证据不足，仍未验证`.
