# Daily Knowledge Curator V1.10.3

Build: `bekki-daily-knowledge-curator-v1-10-3-20260829`

## What the V1.10.2 live test proved

Gemma 4 correctly kept a durable terminology distinction as `stable` and a
person's current affiliation as `changing`. It incorrectly treated the current
complete set of an organization's official units as a member roster and marked
it `changing`. The same output also returned
`lifecycle_proportional=false`, but V1.10.2 normalized persistence to false and
still labeled the overall audit `PASSED`.

## Repairs

- The lifecycle policy now states the generic semantic boundary explicitly:
  canonical organizational units and complete official sets are reviewable;
  a roster is the people or individual members assigned to those units.
- The word "current" no longer makes reusable structural knowledge
  current-turn-only by itself.
- `lifecycle_proportional` evaluates the AI's final decision, not whether it
  agreed with the first proposal.
- A missing, malformed, structurally invalid, or non-proportional audit can no
  longer produce `status=PASSED`. It receives one independent recovery pass and
  otherwise fails closed for Knowledge persistence.
- Even a structurally valid decision is arbitrated by a third AI whenever its
  lifecycle differs from the first AI's reusable classification. Python detects
  only the category disagreement; it has no domain-specific semantic rules.
- The lifecycle audit version is now 2. Older mixed-answer records are
  automatically re-audited, including V1 records that were mistakenly changed
  to `expired/changing`.
- Both new persistence and legacy repair reject results that lack the current
  independent audit certification.

No SNH48-, team-name-, organization-, law-, or domain-specific Python keyword
classifier was added.
