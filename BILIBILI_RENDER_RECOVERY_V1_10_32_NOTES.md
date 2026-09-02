# Bilibili Render Recovery V1.10.32

Build: `bekki-bilibili-render-recovery-v1-10-32-20260831`

## Finding

The failed live run did not receive the real Bilibili search grid. The managed
headless Edge page exposed 46 anchors, one legacy `/video/` link, and zero
video cards. That single BV URL belonged to the compatibility/navigation
shell, so V1.10.31 incorrectly promoted it as a result card and the evidence
model then saw only site chrome.

## Change

- Before Bilibili navigation, derive a normal Windows Edge user agent from the
  actual connected Microsoft Edge version; no browser version is invented.
- Send Chinese-first browser language preferences for the Bilibili tab.
- Search bounded open shadow roots in addition to ordinary document DOM and
  same-page frames.
- Confirm result cards only through a recognized card container or a compact
  image-bearing ancestor.
- Reject raw generic `/video/` links, including the compatibility page's legacy
  `BV1Xx411c7cH` footer/navigation link.
- Keep Bilibili image-backed legacy extraction compatible with V1.10.30.
- Preserve the existing fail-closed behavior for login, consent, CAPTCHA, and
  other platform access controls.

No new AI role, semantic classifier, API dependency, or arbitration gate was
added.

## Expected smoke-test signal

The next Bilibili run should print a line similar to:

```text
[SOCIAL BILIBILI UA] Edge/<installed version>
```

For a rendered result grid, `video_links` and `video_cards` should no longer be
the old `1` and `0` combination, and the candidate sample should contain real
query-related video titles rather than Bilibili footer text.

## Verification

- Bilibili-focused regression suite: 16 tests passed.
- Social Search regression suite: 53 tests passed.
- Full deterministic suite: 928 tests passed; 28 live Ollama tests skipped by
  their existing environment flag.
