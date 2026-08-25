# Bekki Stable V1.3.4.1

Build: `bekki-stable-v1-3-4-1-20260824`

This hotfix changes only social-post location after the live V1.3.4 test showed
that the Xiaohongshu result grid did not expose a conventional title/link pair.

- Uses each post title that already passed the strict date filter.
- Locates that full title directly in the still-open social search page.
- Climbs to the smallest containing card with a visible image and post link.
- If no ordinary link exists, clicks only the exact matched title, observes the
  resulting platform post URL, then restores the search page.
- Keeps the existing grounded detail reader and `social_post` UI card builder.
- Does not change MAGI, recency rules, general search, or either UI file.

Expected live markers:

```text
[SOCIAL POST CANDIDATES] ...
[SOCIAL TITLE LOCATED] 1
[SOCIAL POST MATCHES] 1
[SOCIAL POST OPENED] 1
[SOCIAL CARDS] 1
[CARDS FOR UI] 1
```
