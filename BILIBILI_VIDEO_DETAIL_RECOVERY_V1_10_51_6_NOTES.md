# Bilibili Video Detail Recovery V1.10.51.6

Build ID: `bekki-current-roster-lifecycle-normalization-v1-10-51-9-20260904`

## Live finding

The fixed-site lookup successfully proved `四禧丸子_Official`, filtered every
third-party uploader, selected the official 2022 video, and kept the requested
historical scope. The opened video intermittently reported `cover=0 frames=0`,
however, so only its title reached the fact extractor and the correct safe
result was `LIMITED_EVIDENCE`.

## Recovery

- Wait for title plus video-bound metadata, cover, or a decoded player before
  reading the detail page.
- Read the current video's initial state, visible title/author/description
  nodes, Open Graph metadata, and VideoObject structured data.
- Reject a redirect or player payload whose video ID differs from the selected
  official search result.
- Retry bound cover/frame capture once after a zero-asset first attempt.
- Reopen the selected video once when its first detail read still has no bound
  visual evidence, keeping the stronger of the two reads.
- Pass at most two validated cover/frame images to only that source's fact
  extractor, then remove the image payload before storing or returning browser
  results.
- Keep a cover scoped as a cover and one frame scoped as one moment. Missing
  names or other required facts still return null rather than being guessed.

## Unchanged

- Exact official-account proof and official-video owner binding remain hard
  requirements.
- Explicit 2022 scope cannot be replaced with current data, and current scope
  cannot be satisfied by a 2022 source.
- Knowledge and relationship writes still require the accepted fact and its
  source contract.
- Inline playback, UI, audio, WebView2, and Companion Watch are untouched.
