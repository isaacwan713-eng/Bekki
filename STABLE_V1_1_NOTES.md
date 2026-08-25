# Bekki Stable V1.1

Build: `bekki-stable-v1-1-20260823`

This update keeps the uploaded stable R25 UI byte-for-byte unchanged and fixes
only routing reliability and final-response formatting.

## Routing flow

1. `gemma3:12b` MAGI chooses SEARCH, LOCAL, or COMMAND using the current
   request, then is explicitly released.
2. A result below 0.65 confidence is rejected and one independent AI recovery
   uses `gemma3:4b`. Python validates the closed contract but never chooses the
   semantic lane.
3. Melchior uses a compact, lane-constrained prompt for the detailed mode.
4. A cross-lane result returns to reliable 12B MAGI for an independent audit;
   Melchior replans once against the audited lane.
5. Final replies use an Ollama JSON schema. Invalid JSON receives one 12B
   format-only recovery. A last display-only extractor may preserve the visible
   reply but never memory or actions.

## Fixed manual matrix

| Request | MAGI lane | Melchior mode |
| --- | --- | --- |
| 曼联最近有什么新闻 | SEARCH | NEWS_FEED |
| 打开回收站 | COMMAND | DEVICE_ACTION |
| 帮我在电脑里查找名为 test.txt 的文件 | COMMAND | DEVICE_ACTION |
| 帮我翻译成英文：我今天很开心 | LOCAL | LOCAL_ANSWER |
| 1+1等于多少 | LOCAL | LOCAL_ANSWER |

The QFont point-size warning belongs to the unchanged stable UI and is outside
this routing-only update.
