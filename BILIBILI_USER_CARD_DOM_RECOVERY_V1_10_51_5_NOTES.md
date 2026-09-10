# Bekki Bilibili User Card DOM Recovery V1.10.51.5

Build ID: `bekki-bilibili-user-card-dom-recovery-v1-10-51-5-20260904`

## Live finding

Bilibili's current `/upuser` page visibly rendered the exact
`四禧丸子_Official` account, but the result used markup that did not match the
older user-card CSS selectors. Bekki correctly failed closed, yet could not use
the visible official account.

## Recovery

- Detect a real user card from a numeric `space.bilibili.com` URL, avatar,
  follower count, video count, follow control, and exactly one space identity.
- Repeat the same bounded structural check in Python if Bilibili renames the
  browser-side class hierarchy again.
- Preserve the exact Unicode entity-name and official-marker/verified-badge
  hard gate. Similar accounts and video-card author links remain invalid.
- Reduce Knowledge curator batches from three items to two after the live
  model truncated a relationship-rich third assignment.
- Leave inline playback, UI, audio, WebView2, and Companion Watch untouched.

