# Knowledge Curator Isolation V1.10.54.3

Build: `bekki-knowledge-curator-isolation-v1-10-54-3-20260908`

Parent: Knowledge Judge Isolation V1.10.54.2

## Why this patch exists

The V1.10.54.2 Judge correctly promoted four source-backed AKB48 records, but
the next Curator call placed two records in one prompt together with the full
Topic catalog. The local model repeated one Knowledge ID and answered with an
unrelated 四禧丸子 Topic. Validation rejected that output, so no incorrect Topic
data was committed, but the whole Curator pass stopped and all four valid
AKB48 records remained in the curation inbox.

## Curator isolation contract

- Exactly one verified Knowledge revision is planned per model call.
- The request contains the current item and at most two compact, evidence-
  matching Topic ecosystems; unrelated Topics are absent.
- The request is bounded to 12,000 UTF-8 bytes before it reaches the model
  runtime, so middle truncation is not part of the contract.
- Python computes an immutable curation fingerprint. JSON Schema binds both
  that fingerprint and the one permitted Knowledge ID.
- The subject, subject entity, and Topic title must be grounded in the current
  evidence or in the selected existing Topic.
- Recovery is one fresh compact call. The invalid first output is deliberately
  omitted, preventing it from contaminating the retry.
- Each valid assignment is committed before the next pending item is planned.
  One failed item remains pending with a bounded diagnostic and does not block
  later items. A mixed result is recorded as `COMPLETED_WITH_ERRORS`.

The explicit verified-roster relationship repair remains available, but it is
applied only after both isolated model decisions and only to literal member
names in the current verified claim.

## Preserved behavior

This patch does not change source discovery, Knowledge Judge trust policy,
SQLite migration/history, Curiosity ownership, Topic lifecycle rules,
Bilibili search or playback, the UI, or Companion Watch.

## Validation

After installing, start Bekki once, close it or leave it idle, then run:

```powershell
python knowledge_scheduler.py run --force
powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_CURATOR_ISOLATION_V1_10_54_3.ps1
```

For the live AKB48 recovery case, the scheduler should print four separate
`[NERV KNOWLEDGE CURATOR INPUT]` lines. Each line represents one Knowledge ID.
Valid decisions are logged as `PRIMARY_VALID` or `RECOVERED_VALID`; an isolated
failure is logged as `ITEM WARNING` while later items continue.

