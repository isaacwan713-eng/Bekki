# Bekki Knowledge Relationship Live Recovery Hotfix V1.10.51.1

Build ID: `bekki-bilibili-native-fact-executor-v1-10-51-3-20260903`

This is a data-preserving hotfix for the first live 四禧丸子 relationship test.
SQLite remains schema version 2. Existing JSON/JSONL rollback mirrors and all
`.pre-sqlite-v1.bak` / `.pre-sqlite-v2.bak` migration snapshots are untouched.

## What the live test proved

- V1.10.51 correctly failed closed when both curator passes returned an
  explicit four-member claim with zero relationships.
- The roster claim stayed pending; no partial or guessed relationship was
  written.
- The lifecycle model still labeled the unclosed current roster as stable.
- A neutral request to verify the roster was incorrectly treated as a dispute
  of an adjacent stored setting claim.
- A snippet summary treated encyclopedia and wiki agreement as if it satisfied
  the user's official-source-only rule.

## Hotfix behavior

- After both AI curator passes fail, a narrow structural repair may run only on
  an already-verified atomic claim containing an explicit 2-12 name membership
  list. It copies those exact names, creates neutral `member` entities, and
  emits one `member_of` edge per name. A claim explicitly saying original,
  founding, initial, 创始, 初代, or 最初 uses `original_member_of`.
- Topic selection, subject selection, verification, lifecycle, and all
  non-membership semantics remain AI-owned. Any unrelated contract error still
  fails the batch without writing.
- A current/default people roster without a closed historical scope must be
  `MAINTAINED_SET_OR_STRUCTURE` + `reviewable` with a bounded expiry. The
  lifecycle audit contract is version 9 so V1.10.51 records receive one bounded
  re-audit automatically.
- “请核实 / 请确认 / are you sure” triggers research but no longer enters the
  mutation-capable Knowledge dispute path unless the message explicitly says
  an earlier factual assertion is wrong or needs correction.
- When the user says official sources only, the search-snippet fast path is
  disabled. Casper must open a candidate page, and both page validators must
  confirm that the source itself is official. A wiki, encyclopedia, repost,
  fan account, news summary, or merely “official-related” page is insufficient.

## Expected recovery on the existing live database

Close Bekki, install this build, then start once with `python main.py`. The
scheduled curator should re-audit the pending current roster as reviewable and
finish the previously pending batch. The expected log includes:

`[NERV KNOWLEDGE CURATOR EXPLICIT ROSTER REPAIR] claims=1 relationships=4`

The four active relationships should be:

- 沐霂 `member_of` 四禧丸子
- 又一 `member_of` 四禧丸子
- 梨安 `member_of` 四禧丸子
- 恬豆 `member_of` 四禧丸子

Then close Bekki and run:

`powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_RELATIONSHIP_HOTFIX_V1_10_51_1.ps1`

The test validates the SQLite database, active supporting claims, relationship
direction and provenance, L3 assignment, current-roster expiry, correction
routing, and the official-only summary barrier.

The suspicion that these members are former SNH48 members is still not part of
this claim. Verify each identity separately from authoritative evidence; never
derive it from voice, appearance, fan discussion, or name similarity.
