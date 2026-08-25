# Bekki Stable V1.3.9.4

Build ID: `bekki-stable-v1-3-9-4-20260824`

This patch adds per-post visual grounding to named social research. After a
verified Xiaohongshu title is opened, Bekki captures one bounded screenshot of
that exact detail page. Every screenshot receives an explicit image number and
is sent only with the matching post title, so search-grid images cannot be
silently assigned to another result.

The local vision model may now provide a short description of the post's main
image. It may also read likes, comments, and shares from the detail-page toolbar
only when the number is visibly bound to the correct label or unmistakable
icon. A fixed validator requires the same count in the evidence phrase and the
correct metric marker. 收藏, bookmark, and star counts are always rejected as
shares. Ambiguous or missing values remain unknown.

The existing V1.3.9 behavior remains intact: up to seven recent posts are
briefly described, at most three cards are ranked by grounded visible
interaction, restaurant and product names remain untranslated, and the stable
UI is unchanged.
