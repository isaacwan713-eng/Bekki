# Inline Social Video Theater + Watch Search V1.10.46

Build: `bekki-inline-social-video-theater-watch-v1-10-46-20260902`

## What changed

- Adds the independent `MEDIA_WATCH` route for content the user wants to
  watch. It does not reuse `NEWS_FEED`, `CLAIM_CHECK`, or `SOCIAL_RESEARCH`.
- Supports `EXACT` requests such as `我想看名侦探柯南` and `RANDOM_ONE`
  requests such as `去 B 站找一个下饭视频`.
- Treats every explicitly named website as a hard filter. Results from another
  website cannot pad a failed search.
- Exact searches reject commentary, reactions, clips, trailers, Shorts, or
  summaries unless the user asks for that derivative format.
- Random searches choose from a bounded relevant pool. `换一个` preserves the
  plan and excludes every URL already selected in the current sequence.
- Playable Bilibili and YouTube results ask whether to enter theater mode.
  Unsupported inline sites render a source card only.
- Adds a dark theater layer inside the existing Bekki window. It reparents the
  existing player rather than opening a page or creating another player, so
  audio and playback position survive the transition.
- Adds theater exit, stop, and whole-Bekki fullscreen controls. Esc exits
  theater first; a second Esc can leave whole-window fullscreen.
- Keeps the one-active-player lifecycle and defensive Shiboken cleanup from
  V1.10.44.1, including card replacement, chat clearing, and application close.

## Acceptance examples

1. `去 B 站找一个下饭视频` → one relevant Bilibili result; no YouTube result.
2. `换一个` → a different URL under the same Bilibili/category conditions.
3. `可以` → the selected card begins inside Bekki theater mode.
4. `我想看名侦探柯南` → exact watch discovery; no commentary substitution.
5. `从 example.com 找一个纪录片` → only example.com; link-only if unsupported.

## Validation

```powershell
python -m unittest -v tests.test_media_watch_theater_v1_10_46
python -m unittest discover -s tests -q
```
