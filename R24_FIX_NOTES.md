# Bekki R24 bounded research runtime

Build ID: `bekki-skills-v1-20260818-r24`

R24 fixes the common failure pattern exposed by NEWS_FEED after R23 shopping
succeeded:

- the news query ran after the 20B router without explicitly releasing it;
- news event extraction requested 20B with a 32K context;
- news curation could silently return to the default 20B model;
- the final 12B reply could emit valid JSON inside a Markdown fence, which the
  strict final parser rejected.

The public-web research contract is now consistent:

- NEWS_FEED, FACT_LOOKUP, CLAIM_CHECK and SOCIAL_RESEARCH release the 20B router
  model before loading their research model;
- search-query, news-query, claim-query, consensus and legacy news-ranking
  helpers use `gemma3:12b` with `think=False`;
- source scoring and answer extraction remain on 12B;
- news event extraction uses 12B, reads at most six ranked pages, keeps at most
  4,500 characters per page, and uses a 12,288-token maximum context;
- news curation uses a compact 4K 12B call;
- generic shopping product extraction and comparison use 12B rather than 20B;
- research final replies use 12B with thinking disabled;
- valid JSON inside ```json fences is unwrapped before parsing.

20B remains available for Melchior routing, ordinary conversation,
companionship, content learning, and learned-skill execution. R24 therefore
reduces peak research VRAM without weakening those paths.
