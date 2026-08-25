# Bekki Stable V1.3.4

Build: `bekki-stable-v1-3-4-20260824`

This release fixes one social-research presentation gap while preserving the
Stable R25 UI:

- Binds a recent extracted post title to the real visible platform post link.
- Retains the post's real HTTPS image for the existing UI social-post card.
- Opens up to three grounded posts and reads bounded visible detail text.
- Produces a short, evidence-backed restaurant/post introduction.
- Accepts a restaurant name only when the exact name is present in visible
  evidence; otherwise the post title is used and the missing name is stated.
- Keeps toddler suitability and other missing facilities explicitly unknown.
- Returns structured `social_post` cards so `[CARDS FOR UI]` is no longer zero
  when a grounded recent post and image are available.

Expected live markers:

```text
[SOCIAL POST MATCHES] 1
[SOCIAL POST DETAILS] 1
[SOCIAL CARDS] 1
[CARDS FOR UI] 1
```

No changes were made to `ui.py` or `casper/ui.py`.
