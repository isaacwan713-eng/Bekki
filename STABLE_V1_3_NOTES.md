# Bekki Stable V1.3

Build: `bekki-stable-v1-3-20260824`

This narrow update fixes local file search on top of Stable V1.2. The stable
R25 UI remains byte-for-byte unchanged.

## File-search flow

1. MAGI and Melchior keep the request in COMMAND → DEVICE_ACTION.
2. If the generic application/window planner emits prose or an invalid shape,
   an AI family classifier can hand the request to the bounded file executor.
3. File AI extracts only a literal query, match mode, and target kind. It cannot
   provide a result path.
4. Python recursively scans the real Windows user profile while excluding
   hidden, system, and reparse-point trees. Search is capped at 10 seconds,
   200,000 entries, and 50 results.
5. The direct UI reply contains only paths actually observed during that scan.

## Acceptance request

`帮我在电脑里查找名为 test.txt 的文件`

Expected result: actual matching paths, or an explicit bounded “not found”
message. Bekki must never invent likely Documents/Downloads paths and must not
ask for an application name.

Fact lookup accuracy, recommendations, translation wording, and UI changes are
intentionally outside Stable V1.3.
