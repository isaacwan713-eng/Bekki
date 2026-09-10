# Bilibili Official Publisher Video Discovery V1.10.51.10

Build ID:
`bekki-bilibili-official-publisher-video-discovery-v1-10-51-10-20260904`

## Live failure reproduced

The exact `四禧丸子_Official` Bilibili account and numeric UID were proven,
but the next stage returned to a full-site keyword search. The visible results
were fan videos from other publishers. Exact-author filtering correctly
removed every result:

```text
[CASPER BILIBILI OFFICIAL IDENTITY] status=VERIFIED
[CASPER NATIVE FACT SEARCH] ... candidates=0
[CASPER RESULT] FACT_LOOKUP limited_evidence
```

Because no fact evidence was accepted, the later current-roster lifecycle and
Knowledge refresh code was never invoked.

## Fix

- After profile proof, official discovery opens a bounded video-search page
  below the exact proven numeric UID.
- Roster queries use the literal publisher-local search facet `成员`.
- If that search is empty, the publisher's upload page is tried once.
- Only rendered Bilibili video cards from that exact UID-bound route are
  attributed to the official publisher.
- Another UID, another domain, a bare generic link, or an unverified profile
  cannot receive official-source status.
- The original exact-author full-site search remains a bounded fallback.
- Persisted browser evidence records publisher-page binding version 1.

## Scope

No SQLite schema change is required. V1.10.51.9 current-roster lifecycle
normalization remains intact. The new branch is used only by fixed-Bilibili,
official-only FACT_LOOKUP. Social research, inline playback, audio, Media
Watch, and Companion Watch behavior are unchanged.
