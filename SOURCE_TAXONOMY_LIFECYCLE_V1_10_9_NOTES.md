# Source Taxonomy & Knowledge Lifecycle V1.10.9

Build: `bekki-source-taxonomy-lifecycle-v1-10-9-20260829`

This build repairs three failures observed in the mixed SNH48 acceptance log
without adding an AI role, query gate, or normal-path model call.

- The existing search-query writer preserves a source-language taxonomy when
  its meaning or contrast is part of the question. Entity Scope now records
  source-language semantic boundaries so an erroneous draft gloss cannot
  become authoritative. The existing primary and focused auditors/certifiers
  reject an unestablished equivalence even if the original term is retained in
  parentheses.
- Mixed-answer lifecycle V4 keeps complete official organizational-unit sets
  as persisted `reviewable` knowledge with an AI-selected proportional expiry.
  The expiry ends freshness; it does not auto-update the fact. Current personal
  affiliations remain non-persistent, while fixed historical dates and cohorts
  are judged independently rather than inheriting the current-status lifecycle.
  Existing V3 mixed records are eligible for idle re-audit.
- The existing Daily Knowledge Curator must self-certify entity-boundary and
  relationship consistency in the same output. Related entities may share one
  ecosystem document, but a local organization, parent umbrella, sister
  organization, internal unit, and person retain distinct entity IDs. An
  internal unit cannot be labeled as a sister organization of its parent, and
  topic similarity alone never makes two propositions duplicates.

Python continues to validate structure, opaque identifiers, lifecycle shapes,
and the AI-owned contract outputs. It contains no SNH48, Chinese, entity-name,
or taxonomy keyword rule.
