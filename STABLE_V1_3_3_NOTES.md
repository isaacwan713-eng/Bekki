# Bekki Stable V1.3.3

Build: `bekki-stable-v1-3-3-20260824`

This narrow update improves social-media research quality on top of Stable
V1.3.2. The stable R25 UI remains byte-for-byte unchanged.

## Platform-native query

- Social query generation now uses reliable `gemma3:12b` with a closed JSON
  schema.
- Xiaohongshu queries must contain natural Chinese search concepts while
  preserving proper names such as Arcadia and explicit constraints such as
  两岁小朋友 or 亲子.
- An all-English Xiaohongshu query receives one AI retry and is never silently
  executed as the accepted platform-native query.

## Strict recent-post evidence

- The 12B extractor returns visible titles, authors, times, and discussion
  type.
- Python validates only the evidence boundary: today/yesterday, relative-day,
  full-date, and month-day timestamps are resolved against the runtime date.
- Posts outside the requested window, posts without a resolvable visible date,
  and duplicates are excluded. The recent count is recalculated from the
  validated items instead of trusting an inconsistent model count.

## Bounded social-image understanding

- The managed social browser captures at most three 800x600 visible JPEG
  frames while scrolling the current result page.
- Local `gemma3:12b` receives those frames and describes relevant visible
  content, text, and uncertainty.
- A visual observation is retained only when the screenshot visibly associates
  it with the exact title of a post that already passed the time filter.
- Images cannot establish the date, author, restaurant identity, safety, or
  truth of a claim. The visual prompt blocks identity and sensitive-attribute
  inference.

## Acceptance request

`去小红书搜索最近一周 Arcadia 适合两岁小朋友的餐厅推荐`

Expected logs include a Chinese `[SOCIAL QUERY]`, filtered `[SOCIAL EVIDENCE]`,
and `[SOCIAL VISUAL EVIDENCE]`. Old 2025 dates and an out-of-window `05-10`
must not remain in `items`; a visible `2天前` item may remain with a
`resolved_date` inside the seven-day window.
