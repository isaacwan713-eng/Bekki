# Bekki NERV Learning V1.3

Build ID: `bekki-nerv-learning-v1-3-20260825`

This release adds safe forgetting for verified reusable skills without changing
the Stable V1.3.9.5 UI.

## User flow

1. Ask: `忘掉打开 FM26 战术文件夹这个技能`
2. Bekki resolves one exact verified skill and asks for confirmation.
3. Reply `确认忘掉` to delete it, or `取消` to keep it.
4. Ask `你目前学会了哪些操作？` to verify the skill is no longer active.

The first turn never deletes anything. Only Casper can remove the verified
skill, and its API requires literal `confirmed=True`. The matching and
confirmation decisions use `gemma3:12b`, which is unloaded immediately after
each focused decision. Reminder deletion remains a separate task-store action.

Validation: 624 tests passed, 4 platform-dependent tests skipped. `ui.py` and
`casper/ui.py` are byte-identical to Bekki Stable V1.3.9.5.
