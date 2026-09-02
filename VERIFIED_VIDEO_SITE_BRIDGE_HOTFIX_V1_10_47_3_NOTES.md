# Verified Video Site + Companion Bridge Hotfix V1.10.47.3

Build: `bekki-verified-video-site-bridge-hotfix-v1-10-47-3-20260902`

## What changed

- A domain named by the user is now only a site condition, not proof that the
  site is a video website.
- Unknown sites must expose repeated same-domain video detail URLs together
  with video taxonomy or actual media structure before Bekki registers them.
- Rejected sites cannot fall through to ordinary Google/Bing results and be
  presented as watch sources.
- Verified sites persist their same-domain search template and public aliases
  in `data/verified_video_sites.json`; the installer preserves this data.
- `iyf.tv` can be discovered through its native search and return the exact
  `名侦探柯南` show page. It remains link-only until it has a separately
  supported inline player contract.
- Companion Watch now sends panel events through qtwebview2 `DictJsBridge`
  instead of posting raw JSON into the library's internal RPC channel.

## Verification contract

Registration requires either:

- at least six distinct video-detail links plus at least two video taxonomy
  signals; or
- at least three distinct video-detail links, one taxonomy signal, and a real
  media element.

User wording, a single embedded player, and incidental `/video` links do not
create a registry entry.
