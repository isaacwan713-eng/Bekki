# Bekki Stable V1.3.9.2

Build ID: `bekki-stable-v1-3-9-2-20260824`

This patch addresses the live Xiaohongshu test where seven recent posts were
extracted but only one title-bound page and one card were produced.

- Candidate post links are accumulated at every bounded search-page viewport.
- Exact recent titles are resolved from the top of the virtualized result grid
  through as many as eight bounded viewport scans.
- A clicked post restores both the authorized search URL and prior scroll
  position before the remaining titles are resolved.
- The final social reply is rendered from all supplied structured summaries,
  guaranteeing one simple numbered description per retained post, up to seven.
- The highest one-to-three grounded cards remain ranked by visible interaction.
- Unlabeled search-grid counts are shown as generic visible interaction, never
  mislabeled as likes.

Python owns bounded navigation, evidence validation, and display formatting.
AI still owns MAGI routing, social text/image understanding, post descriptions,
and extraction of visibly labeled likes, comments, and shares.

The stable UI is unchanged.
