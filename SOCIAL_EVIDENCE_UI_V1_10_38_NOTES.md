# Bekki Social Evidence UI V1.10.38

Build ID: `bekki-social-evidence-ui-v1-10-38-20260831`

## What changed

- Keeps `gemma4:12b`, `num_ctx=8192`, and the persistent minimized Edge
  profile so the 16 GB GPU budget remains suitable beside a foreground game.
- Captures title-bound post media or result cards with a short Playwright
  timeout and direct CDP fallback, avoiding the prior 30-second font wait.
- Caches at most 160 social evidence images and shows up to two images beneath
  each of as many as five social cards. Images are clickable local evidence.
- Marks fallback cards as `search_only`; a visible `$25` roast-duck result can
  be shown while the unseen restaurant name remains unknown.
- Treats `250`, `190`, `1.9k`, and `15🍞` as price evidence in a visibly clear
  sale/menu/card-price context even without a currency label. `1.9k` is
  normalized to 1900, currency stays unknown, and asking/displayed prices are
  not promoted to completed sales or market-wide values.
- Adapts generic Reddit intent to the community language while preserving
  names and `r/community`. A zero-result plan may retry one broader bounded
  platform-native query.
- Maps “讨论最多” to Reddit `sort=comments` with the requested time filter,
  parses votes and comments separately, and ranks by comments.
- Rejects keyword-only collisions and prevents one opened post from supporting
  a high-confidence aggregate trend. At least three opened relevant posts are
  required for an aggregate claim.
- Rejects generic Rednote shells and Reddit login artwork as post visual
  evidence while retaining compatibility with legitimate short text posts.

## Suggested Windows checks

1. `去小红书搜索最近一个月 aespa karina 小卡卡价 top 10`
2. Confirm that values such as `250` and `1.9k` appear with “币种未注明”.
3. Confirm that one or two screenshots appear under each selected result card.
4. `去 Reddit 的 r/robotics 搜索最近一个月大家讨论最多的家用机器人问题`
5. Confirm the URL uses `sort=comments&t=month` and results rank by comments.
6. Confirm background Edge remains minimized and the saved account state is
   reused after restarting Bekki.

X and Instagram remain deferred because their authenticated flows have not yet
been tested in this release.

## Validation

- `python -m unittest discover -s tests -p 'test_*.py'`
- 974 tests passed; 28 platform/environment-dependent tests skipped.
