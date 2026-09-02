# Bilibili Card-First DOM V1.10.31

Build: `bekki-bilibili-card-first-v1-10-31-20260831`

## Finding

V1.10.30 proved that the search query and RELEVANCE scope were correct, but
only two generic allowed links reached the evidence packet. Those two items
were not the number of Bilibili search results; they were the number of links
recognized by the bounded generic DOM scan. Hidden navigation can precede the
visible video grid by hundreds of anchors.

## Change

- Select every visible `/video/` and `/bangumi/play/` link before ordinary
  anchors, instead of treating the first N page links as the result set.
- Read current `.bili-video-card`, `.video-list-item`, and related card
  containers and preserve title attributes, visible metadata, and thumbnails.
- Read up to 12 same-page frames and merge duplicate URLs across them.
- Prefer actual video cards whenever both cards and generic profile links are
  present.
- Wait up to seven seconds for Bilibili's SPA result list to attach.
- Log `frames`, `anchors`, `video_links`, `video_cards`, and three bounded
  candidate samples for an unambiguous Windows diagnosis.

No new AI role, semantic classifier, or arbitration gate was added.

## Verification

- 31 focused Social Search tests passed.
- Full deterministic suite: 920 tests passed; 28 live Ollama tests skipped by
  their environment flag.
