# Discussion Feed V1.10.41.8

- Adds `DISCUSSION_FEED` as a dedicated SEARCH mode, separate from
  `NEWS_FEED`, `CLAIM_CHECK`, and platform-native `SOCIAL_RESEARCH`.
- Routes a pure closed claim such as `卡黄闹翻了吗？` to `CLAIM_CHECK`, while
  the mixed/open request `卡黄是闹翻了吗，她们为什么会闹翻？` routes to
  `DISCUSSION_FEED` because the multi-source causal summary is the controlling
  requirement.
- Uses general web discovery for Zhihu, Quora, Tieba, independent forums, Q&A
  pages, fan discussions, blogs, and web-indexed posts. No native platform is
  guessed and `social_platforms` remains empty.
- Keeps explicit Bilibili, Xiaohongshu, Reddit, X, and Instagram requests on
  the existing platform-native `SOCIAL_RESEARCH` path.
- Selects varied relevant discussion pages, reads each page, extracts only
  attributed claims and interpretations, and synthesizes repeated themes,
  single-source views, disagreement, and context without a consensus vote.
- Never treats repeated discussion as confirmation and never labels discussion
  pages as news.
- Binds every selected source to one unified context, optional page image, and
  original-link card.
- Fails closed when no relevant discussion can be read.
- Includes Social Claim Grounding V1.10.41.7 and all prior UI, social evidence,
  curiosity, and user-message completeness fixes.
