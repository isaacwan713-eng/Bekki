# Bekki Stable V1.3.1

Build: `bekki-stable-v1-3-1-20260824`

This hotfix completes the exact local-file search repair started in Stable
V1.3. The stable R25 UI remains byte-for-byte unchanged.

## Corrected file-search flow

1. MAGI routes the request to COMMAND and Melchior chooses DEVICE_ACTION with
   `device_scope=FILE_ACTION`.
2. Casper uses that scope to bypass the unrelated application/window planner.
   It cannot emit prose or guessed paths before file search starts.
3. Reliable `gemma3:12b` chooses the authoritative file action and is released.
   A named-file request must select `SEARCH_FILES`.
4. The detailed planner receives a schema whose action enum contains only that
   authoritative action, preventing it from copying a `LIST_FOLDER` example.
5. Python recursively scans the real Windows user profile while excluding
   hidden, system, and reparse-point trees. Search is capped at 10 seconds,
   200,000 entries, and 50 results.
6. The direct reply contains only paths actually observed during that scan.

## Acceptance request

`帮我在电脑里查找名为 bekki_search_test.txt 的文件`

Expected logs include `device_scope: FILE_ACTION`,
`[FILE ACTION GATE] SEARCH_FILES`, and a final `searched_files` result. Bekki
must not print a guessed `YourUsername` path and must not merely list Downloads.

Other search accuracy, recommendations, UI redesign, and avatar work remain
outside this narrow hotfix.
