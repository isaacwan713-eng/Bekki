# Bekki Knowledge Relationship Grounding V1.10.51

Build ID: `bekki-bilibili-native-fact-executor-v1-10-51-3-20260903`

This update keeps SQLite schema version 2. It changes Knowledge semantics and
validation only; it does not replace, delete, or rewrite the Phase 1 or Phase 2
migration snapshots.

## What changed

- A complete current official roster is reusable `reviewable` knowledge with a
  bounded expiry. It is not `FIXED_HISTORY` unless the claim carries a valid
  closed-period temporal scope.
- An explicit multi-name member list must produce one relationship for every
  listed member. Partial relationship sets fail the curator contract and get
  one recovery attempt.
- Membership direction is canonical: person/character `member_of` group. A
  claim explicitly saying original/founding members uses
  `original_member_of`.
- Every relationship stores stable semantic identity, supporting Knowledge
  IDs, exact claim evidence, knowledge type, temporal scope, status, and
  relationship-contract version.
- Related entity names and relationship evidence must occur in the exact
  atomic claim. Other text from the same answer cannot silently create an
  adjacent relationship.
- Topic titles, aliases, entity aliases, and keywords are kept only when they
  are grounded in verified source context. Unsupported generated translations
  such as `Sihixian` are removed automatically.
- Legacy group-to-person membership edges are reversed when entity types make
  the old direction unambiguous. Unsupported legacy edges are retained in a
  topic-local quarantine instead of being exposed as knowledge.
- Active relationship views are intersected with the authoritative SQLite
  Knowledge ledger. Expired, disputed, superseded, duplicate, or conflicting
  support is not exposed even if an older topic copy remains on disk.
- A claim that produces a semantic relationship must be assigned
  `L3_RELATIONSHIPS`. Legacy L1/L2 assignments are cleared and queued for the
  normal Topic Lifecycle reassessment.

## 四禧丸子 test behavior

The prior run saved the verified setting claim but dropped the four-member
roster because the lifecycle auditor incorrectly selected `FIXED_HISTORY`
without a historical period. This build cannot reconstruct a missing claim
from neighboring answer text. After installation and one startup, repeat the
same lookup:

> 请核实“四禧丸子”当前官方公开的完整成员名单。只接受该组合的官方账号或官方资料；不要根据声音、外形、粉丝讨论或疑似身份推断。

If the accepted evidence supports the complete current official roster, the
expected result is one reviewable roster claim and four active edges:

- 沐霂 `member_of` 四禧丸子
- 又一 `member_of` 四禧丸子
- 梨安 `member_of` 四禧丸子
- 恬豆 `member_of` 四禧丸子

If you also want the debut/founding roster, ask for it separately and require
the official announcement date. A dated closed historical claim can then use
`original_member_of` without being confused with the current reviewable roster.

The suspicion that all four are former SNH48 members remains outside
Knowledge. Test it as a separate fact lookup, one person per atomic claim, and
accept only independently verified results. Do not infer identity from voice,
appearance, fan discussion, or name similarity.

## Install and validate

1. Close Bekki and its scheduled Knowledge worker.
2. Extract this ZIP outside the installed `AI-Assistant` directory.
3. Run `INSTALL_STABLE_V1.bat`.
4. Start once with `python main.py`; this applies bounded semantic migration to
   existing topic documents.
5. Close Bekki, then run:

   `powershell -ExecutionPolicy Bypass -File .\TEST_KNOWLEDGE_RELATIONSHIP_V1_10_51.ps1`

The test first runs eight isolated regression cases, then checks the live
SQLite database, relationship provenance, direction, active support, semantic
contract, L3 state, and the optional 四禧丸子 roster state. A zero roster-edge
count means the old dropped roster still needs the lookup above; a complete
successful rerun produces exactly four.
