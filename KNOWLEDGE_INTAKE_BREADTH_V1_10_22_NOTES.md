# Bekki Knowledge Intake and Curiosity Breadth V1.10.22

Build ID: `bekki-knowledge-intake-breadth-v1-10-22-20260830`

This patch closes two V2 Knowledge gaps without adding another AI role.

## Accepted FACT_LOOKUP intake

- An ordinary low-risk FACT_LOOKUP that has already passed Casper's evidence
  process can now contribute reusable claims to Knowledge.
- Capture runs on NERV's existing background writer after the reply, so it
  cannot delay, reject, replace, or rewrite the answer shown to the user.
- The existing partitioner separates atomic claims and the existing lifecycle
  auditor makes the final stable, reviewable, or transient decision.
- External-AI fallback answers and objective-correction answers retain their
  existing governed paths and are not captured twice.
- Current people rosters and current personal affiliations remain
  current-turn-only.
- A historical people roster can persist only as FIXED_HISTORY when Casper's
  accepted temporal validation supplies an exact closed snapshot or season.
  The exact source-supported period is part of both claim text and identity.
- A maintained formal unit set remains distinct from the people assigned to
  those units and may be stable or reviewable.

## Curiosity breadth

- The existing Writer now declares a foundation facet, its breadth relation to
  the completed turn, and whether the breadth is proportionate.
- After a FOUNDATION list, roster, affiliation, or organizational-definition
  turn in a new or developing topic, another role, newest-member, status, or
  list-slice question is the same narrow facet.
- Bekki instead moves to an approachable distinct facet such as people,
  history, works, performances, events, stories, relationships, culture, or
  ordinary behavior.
- The existing Selector audits the literal question before sending it. No
  third critic, new model call, Python keyword classifier, or domain-specific
  SNH48 rule was introduced.

## Expected runtime evidence

After a normal accepted low-risk fact answer, the background log reports:

```text
[NERV FACT KNOWLEDGE INTAKE] status=COMPLETED persisted=<count> reason=<reason>
```

`persisted=0` is expected for a current people roster or another transient
fact. An exact completed historical snapshot may report `persisted=1`.
