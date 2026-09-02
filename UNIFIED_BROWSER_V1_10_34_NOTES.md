# Unified Browser V1.10.34

V1.10.33 reached its browser migration path but then logged:

`RuntimeError('Bekki could not close its dedicated headless social browser.')`

The failure happened before Bilibili navigation, so neither DOM results nor the
page-native response reader had a chance to run. It also exposed a broader
architectural problem: Bekki maintained a social browser on port 9223, a Casper
research browser on port 9224, and an additional temporary headless browser for
rendered-page fallback.

V1.10.34 replaces those paths with one Bekki Browser:

- One normal Microsoft Edge process on port 9225.
- One isolated `%LOCALAPPDATA%\Bekki\unified_browser_profile` profile.
- Web search, news, recommendations, product and download pages, generic
  rendered-page fallback, Bilibili, Reddit, Xiaohongshu, Instagram, and X all
  connect to that same session.
- The browser starts minimized with background rendering enabled. A protected
  event or user-verification handoff displays the same profile instead of
  stopping and reopening it.
- Each operation closes only the pages it created. Social cleanup recognizes
  social domains and does not close general research tabs or the process.

The first unified-browser call performs a bounded Windows migration cleanup.
It targets an Edge process only when its command line contains both an old
Bekki debugging port (`9223` or `9224`) and an old Bekki profile marker
(`social_browser_profile` or `casper_browser_profile`). It does not target the
user's normal Edge profile. Cleanup is best-effort and cannot block the new
port-9225 browser from starting.

Useful diagnostics:

- `[BEKKI BROWSER] mode=normal port=9225 session=started` means the unified
  normal Edge was launched.
- `[BEKKI BROWSER] mode=normal port=9225 session=attached` means Bekki reused
  the existing unified session.
- `[BEKKI BROWSER LEGACY CLEANUP] processes=N` means `N` retired Bekki Edge
  processes were removed during the one-time migration.
- `[SOCIAL BILIBILI RESPONSE] candidates=N` and
  `[SOCIAL BILIBILI RESPONSE MERGE] candidates=N` retain their V1.10.33
  meanings.

The unified profile remains separate from the user's personal Edge data. Login,
consent, CAPTCHA, and other platform controls remain user-controlled and
fail-closed. No new AI role or arbitration gate was added.
