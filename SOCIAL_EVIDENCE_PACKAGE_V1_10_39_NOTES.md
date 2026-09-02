# Bekki Social Evidence Package V1.10.39

Build ID: `bekki-social-evidence-package-v1-10-39-20260831`

## What changed

- Xiaohongshu cards show up to three original post images in carousel order,
  plus one complete body-text screenshot and the original-post link.
- Reddit cards show exactly one post-body screenshot and the original link;
  search-page screenshots and login artwork are excluded.
- A search-result crop is used only when an opened post is unavailable and is
  visibly labeled `搜索结果预览`.
- The local model receives at most two images per request. A four-asset
  Xiaohongshu post uses two bounded visual passes, while two Reddit text posts
  share one text-only introduction pass.
- Reddit DISCUSSION searches preserve the requested issue/problem facet, use
  `sort=comments` with the requested time window, lead with visible comment
  counts, and describe only the verified sample.
- PRICE ranking is separate from popularity. Contextual shorthand including
  `250`, `190`, `1.9k`, `15🍞`, and `330💼` remains usable price evidence even
  when currency is absent; asking/displayed values are not promoted to sales
  or market-wide prices.
- Bilibili accepts only a native search row or a strict image-bearing video
  card. Its legacy footer BV link can no longer suppress the single bounded
  refresh used after an empty first load.
- The persistent minimized Edge profile, `gemma4:12b`, and `num_ctx=8192`
  remain unchanged for practical use beside a foreground game on a 16 GB GPU.

## Suggested Windows checks

1. Search Bilibili for `又一充电中 袁雨桢`; confirm an initially empty page is
   refreshed once and produces real video cards.
2. Search Xiaohongshu for a multi-image card-price post; confirm labels
   `图 1`, `图 2`, `图 3`, and `正文`, followed by `打开原帖`.
3. Confirm five-image notes stop after the first three post images.
4. Search Reddit r/robotics for the last month's most-discussed home-robot
   problems; confirm a problem-focused query, comment-count order, one body
   screenshot per card, and sample-scoped wording.
5. Confirm the shared Edge window remains minimized and login state survives
   a Bekki restart.

X and Instagram remain deferred pending authenticated-flow testing.

## Validation

- `python -m unittest discover -s tests -p 'test_*.py'`
- 985 tests passed; 28 platform/environment-dependent tests skipped.
