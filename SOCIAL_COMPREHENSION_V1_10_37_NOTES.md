# Bekki Social Comprehension V1.10.37

Build ID: `bekki-social-comprehension-v1-10-37-20260831`

## What changed

- Keeps `gemma4:12b`, `num_ctx=8192`, and the existing unified Edge process.
- Reads each selected post independently so malformed output affects only that
  post.
- Supplies up to two title-bound images per post: a dominant-media crop and a
  wider visible page frame.
- Replaces the restaurant-specific detail schema with universal text findings,
  image findings, exact evidence quotes, request relevance, and uncertainty.
- Stops asking the vision model to guess likes, comments, or shares.
- Adds one text-only retry when a multimodal response is malformed.
- Adds a grounded cross-post synthesis that answers the exact request, checks
  location/currency/identity/unit conflicts, and refuses unsupported rankings.
- Resolves Reddit timestamps such as `4d`, `12h`, and `30m` and hard-bounds an
  explicit `r/community` search to that community.
- Removes social automation's `bring_to_front()` calls and minimizes the Edge
  window through CDP. Interactive login and background research use the same
  `%LOCALAPPDATA%\Bekki\unified_browser_profile` account state.

## Expected new logs

- `[BEKKI BROWSER] mode=background ...`
- `[BEKKI BROWSER BACKGROUND] window=minimized ...`
- `[SOCIAL INTRO PROMPT BATCH] posts=1 ... images=1|2 num_ctx=8192`
- `[SOCIAL UNDERSTANDING RETRY] ... mode=text_only` only after malformed vision
  JSON.
- `[SOCIAL SYNTHESIS PROMPT] posts=N ... num_ctx=8192`
- `[SOCIAL SYNTHESIS] findings=N limitations=N confidence=...`
- `[SOCIAL REDDIT SCOPE] communities=...` for an explicit subreddit.

## Suggested Windows checks

1. `去小红书搜索 Arcadia 亲子餐厅`
2. `去小红书搜索最近一个月 aespa karina 小卡卡价 top 10`
3. `去 Reddit 搜索 microduck review r/robotics`
4. Confirm that automated Edge tabs do not appear on the main screen.
5. Use the visible human-handoff window to sign in once, close Bekki, restart
   it, and confirm that background research remains signed in.

The current release understands the visible main media and wider page frame.
It does not automatically click through every image in a carousel; unseen
carousel pages remain unknown instead of being inferred.

## Validation

- `python -m unittest discover -s tests`
- 964 tests passed; 28 platform/environment-dependent tests skipped.
