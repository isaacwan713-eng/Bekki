# Bilibili Visible Results V1.10.30

Build: `bekki-bilibili-visible-results-v1-10-30-20260831`

## Problem

A Bilibili search could visibly render many matching videos while Bekki's
generic body-text snapshot contained only site navigation and footer text.
Only the first 60 anchors were inspected, so navigation links could also crowd
real video links out of the bounded candidate set. Bilibili search thumbnails
used `.jpg@...avif` transformation URLs that some Qt installations could not
decode.

## Change

- Scan a bounded 500 anchors and retain up to 400 unique DOM candidates before
  the existing platform URL filter selects at most 30 public post candidates.
- Prefer known visible result-card ancestors and merge duplicate hrefs so the
  richest visible text and available thumbnail survive.
- Put literal visible result-card text before generic page chrome in the same
  existing Social Evidence call.
- Normalize Bilibili `hdslb.com` transformed AVIF thumbnail URLs to the same
  source image's original JPEG/PNG/WebP URL in both browser extraction and the
  asynchronous result-card image loader.
- Keep screenshots supplied by the user outside Bekki's runtime evidence.

No new AI role, semantic Python classifier, or arbitration gate was added.

## Verification

- 27 focused Bilibili, Reddit, relevance-scope, and legacy Social Search tests
  passed.
- Full deterministic suite: 916 tests passed; 28 live Ollama tests skipped by
  their environment flag.
