# Bekki Bilibili and Reddit Social Search V1.10.28

Build ID: `bekki-social-bilibili-reddit-v1-10-28-20260830`

## Changes

- MAGI and Melchior can select `bilibili` and `reddit` through the existing
  `SOCIAL_RESEARCH` contract.
- Casper opens the native Bilibili and Reddit search pages in Bekki's existing
  managed Edge profile.
- The existing social-query AI preserves source-language names, aliases,
  slang, mixed-language terms, UIDs, BV/AV identifiers, and subreddit names.
- Bilibili evidence is bounded to public video, opus, article, live-room,
  profile, and short-link targets from Bilibili domains.
- Reddit evidence is bounded to post permalinks and may be text-only.
- Xiaohongshu and Instagram retain their existing image-first candidate rule.
- Login, consent, CAPTCHA, and platform access controls are not bypassed; an
  unreadable page fails closed.

This release adds no AI model, semantic Python classifier, or routing gate.

## Suggested smoke tests

```text
去B站搜索 又一充电中 袁雨桢
去Reddit搜索 microduck review
```

Expected routing includes `SOCIAL_RESEARCH` with `bilibili` or `reddit`, and
the `[SOCIAL QUERY]` log keeps the meaningful source expressions unchanged.
