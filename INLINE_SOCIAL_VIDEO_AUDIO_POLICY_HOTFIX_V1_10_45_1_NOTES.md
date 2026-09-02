# Inline Social Video Audio Policy Hotfix V1.10.45.1

Build: `bekki-inline-social-video-audio-policy-hotfix-v1-10-45-1-20260902`

## Finding

V1.10.45 reported `muted=false, playing=false` on Bilibili. That rules out
WebView2's global mute state: the embedded document had not begun producing
audio. The native Qt play-button click does not automatically count as a web
document user gesture, so Chromium can still reject audible autoplay.

## Fix

- Adds `--autoplay-policy=no-user-gesture-required` to
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` before importing/creating the first
  WebView2 control.
- Preserves any existing WebView2 arguments and adds the flag idempotently.
- Applies only on Windows.
- Retains the verified-player navigation boundary and the lazy card contract:
  no WebView exists until the user clicks Bekki's play control.
- Retains Bilibili `muted=0` and `CoreWebView2.IsMuted = False` from V1.10.45.
- Rechecks observable audio state after 250 ms, 1 second, and 2.5 seconds.

## Expected test log

At application startup:

`[INLINE VIDEO AUDIO POLICY] enabled=true flag=--autoplay-policy=no-user-gesture-required`

After Bilibili playback starts, one of the delayed checks should report:

`[INLINE VIDEO AUDIO] platform=bilibili ... muted=false playing=true`

If all delayed checks remain `playing=false`, click Bilibili's own play control
inside the video once. That is a direct browser gesture and is the final
platform-native fallback.

