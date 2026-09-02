# Media Watch Native Discovery Hotfix V1.10.46.1

Build: `bekki-media-watch-native-discovery-hotfix-v1-10-46-1-20260902`

## Fixed

- `MEDIA_WATCH` now searches Bilibili and YouTube on the platform's own
  rendered search page before trying Google or Bing.
- A valid native result stops discovery immediately, so `去 B 站找一个下饭视频`
  no longer depends on a search engine understanding `site:bilibili.com/video`.
- Bilibili's structured search-response candidates preserve title,
  description, author, publication date, cover, and the verified video URL.
- Native results still pass the existing website, topic, derivative-content,
  and inline-player checks. Unrelated native cards cannot suppress the bounded
  web-search fallback.
- Category phrases with a generic media suffix use one bounded subject token:
  for example, `下饭视频` may match a native title containing `下饭`, while an
  unrelated video still fails closed.
- Explicit source requests remain hard conditions. A Bilibili-only request
  never opens YouTube native search and never accepts a YouTube result.

## Expected runtime path

For `去 B 站找一个下饭视频`, a successful native run logs:

```text
[MEDIA WATCH NATIVE] platform=bilibili candidates=<n>
[CASPER MEDIA WATCH] mode=RANDOM_ONE sites=bilibili.com playable=true candidates=<n>
```

`[CASPER BROWSER SEARCH FALLBACK]` should appear only if native Bilibili
results are empty or all fail the relevance contract.

## Validation

```powershell
python -m unittest -v tests.test_media_watch_theater_v1_10_46
python -m unittest discover -s tests -q
```
