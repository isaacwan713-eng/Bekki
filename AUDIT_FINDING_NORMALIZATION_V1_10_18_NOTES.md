# Audit Finding Normalization V1.10.18

Build: `bekki-audit-finding-normalization-v1-10-18-20260829`

This release fixes a contradiction in the existing External-AI Answer Auditor.
The model could previously mark an answer direct, complete, policy-compliant,
conflict-free, cleanable, and highly confident, then still emit a global
`REJECT` label.

The same single audit call now returns only model-owned semantic findings and a
canonical answer extracted from the candidate. Python performs a generic
contract mapping:

- all required semantic findings pass, confidence is at least 0.80, and a
  canonical core exists: `AUTO_VERIFY`;
- otherwise: `REJECT`;
- omitted candidate assertions produce `USE_CANONICAL_CORE`; a fully retained
  candidate produces `USE_AS_IS`.

Python does not decide whether an SNH48 Team, person, date, event, or other fact
is correct. It does not use domain keywords or select claims. The auditor still
owns scope, completeness, policy, conflict, confidence, and the exact retained
answer. The mapping only prevents an extra verdict field from contradicting
those findings.

The canonical answer is required for every successful audit and is used for
both the user reply and Knowledge persistence. Rejected audits use the internal
`NO_COMPLETE_CORE` sentinel, which is never shown or stored.

No AI role, AI gate, external request, or model call was added.
