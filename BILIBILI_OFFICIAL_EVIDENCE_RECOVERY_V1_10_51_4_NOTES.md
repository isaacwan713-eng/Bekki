# Bekki Bilibili Official Evidence Recovery V1.10.51.4

Build ID: `bekki-bilibili-official-evidence-recovery-v1-10-51-4-20260903`

This is a data-preserving safety hotfix on V1.10.51.3. SQLite stays at schema
version 2. Inline video playback, audio, theater mode, WebView2, and Companion
Watch are deliberately unchanged.

## Live failure addressed

The strict official-only 四禧丸子 lookup accidentally treated profile links
inside unrelated video cards as native account results. Two model validators
then accepted an ordinary uploader as official, producing an unrelated roster.
That answer entered the flat Knowledge ledger, while the curator repeatedly
retried an incomplete relationship plan.

## Official identity contract

- Strict official Bilibili facts first search the native `/upuser` surface for
  the exact requested entity.
- A profile must be a real account-result card and must have either a verified
  badge or an explicit official marker in its account name.
- Similar-looking entities remain distinct, including `四禧` versus `四喜`.
- Videos are eligible only when their author URL or exact author name matches
  the one proven account.
- Missing or ambiguous identity proof returns limited evidence. AI validators
  cannot override this deterministic rejection.
- The identity basis, publisher, fixed-source contract, and proof status are
  retained in SQLite Knowledge provenance.

## Knowledge recovery

On first startup, a legacy verified claim is quarantined only when all of the
following are true: it came from `casper_audited_fact_lookup`, its original
request fixed research to official sources, and none of its evidence rows has
deterministic official-identity proof. The record and revision history are
preserved, but the claim becomes disputed and leaves active retrieval,
relationships, and curator input pending reverification.

## Lifecycle and curator recovery

- A roster can use `FIXED_HISTORY` only when the proposed closed period is
  visible in the claim. An invisible model-invented date cannot freeze a
  current roster; it is recovered to reviewable maintained-set Knowledge.
- Explicit member relationships can be repaired when the group name lives in
  the record's separate `subject` field and the claim contains only the list.
- A failed curator run receives a 15-minute automatic retry cooldown. A manual
  `force=True` run remains available.

Run:

`powershell -ExecutionPolicy Bypass -File .\TEST_BILIBILI_OFFICIAL_EVIDENCE_RECOVERY_V1_10_51_4.ps1`
