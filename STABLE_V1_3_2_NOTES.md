# Bekki Stable V1.3.2

Build: `bekki-stable-v1-3-2-20260824`

This narrow update fixes explicit social-platform routing on top of Stable
V1.3.1. The stable R25 UI remains byte-for-byte unchanged.

## Corrected social-search flow

1. Reliable `gemma3:12b` MAGI still chooses SEARCH, LOCAL, or COMMAND.
2. The same AI result now also returns a closed social scope and a validated
   platform list containing only x, instagram, or xiaohongshu.
3. An explicit request to search a named social platform becomes
   `SOCIAL_RESEARCH` immediately. Compact Melchior cannot reinterpret it as
   LOCAL_ANSWER or NEWS_FEED.
4. The reliable model is released exactly as before; no additional 12B call is
   added to ordinary or social requests.
5. Python validates only the closed AI result. It does not select social
   routing from keywords.

## Acceptance request

`去小红书搜索最近一周 Arcadia 适合两岁小朋友的餐厅推荐`

Expected logs include:

- MAGI route with `social_scope: SOCIAL_RESEARCH`
- `social_platforms: ["xiaohongshu"]`
- `[MELCHIOR SOCIAL ROUTE] ["xiaohongshu"]`
- `[melchior MODE] SOCIAL_RESEARCH`
- `[SOCIAL QUERY]` followed by either readable `[SOCIAL EVIDENCE]` or an
  explicit social-browser error that can be diagnosed separately

The request must not run Google/Bing NEWS_FEED and must not cite Tripadvisor or
Yelp as if they were Xiaohongshu results.

Browser compatibility, social-site login or anti-bot behavior, UI redesign,
and unrelated research accuracy remain outside this routing-only update.
