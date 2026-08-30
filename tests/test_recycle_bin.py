import unittest
import sys
import types
from unittest.mock import patch

from casper import recycle_bin


class RecycleBinTests(unittest.TestCase):
    def test_ai_plan_distinguishes_open_window_from_listing(self):
        stale_context = "User: 回收站里有什么？\nAssistant: 正在读取项目"
        model = unittest.mock.Mock(return_value="OPEN_RECYCLE_BIN")
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": tools_stub}):
            action = recycle_bin._plan("打开回收站", stale_context)

        self.assertEqual(action, "OPEN_RECYCLE_BIN")
        prompt_input = model.call_args.args[1]
        self.assertLess(
            prompt_input.index("打开回收站"),
            prompt_input.index("回收站里有什么"),
        )
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma4:12b")
        self.assertGreaterEqual(model.call_args.kwargs["num_predict"], 256)

    def test_lists_bounded_recycle_bin_items(self):
        items = [
            {
                "id": "item-id",
                "name": "old.txt",
                "shell_path": "C:/$Recycle.Bin/recycled.txt",
                "original_location": "C:/Users/Test/Desktop",
                "date_deleted": "2026-08-16",
                "size": "12",
            }
        ]
        with patch.object(
            recycle_bin, "_plan", return_value="LIST_RECYCLE_BIN"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="NOT_RESTORE",
        ), patch.object(
            recycle_bin, "_discover_items", return_value=items
        ):
            result = recycle_bin.execute("回收站里有什么？", "")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "listed_recycle_bin")
        self.assertEqual(result["items"][0]["id"], "item-id")
        self.assertNotIn("shell_path", result["items"][0])

    def test_opens_recycle_bin_window(self):
        with patch.object(
            recycle_bin, "_plan", return_value="OPEN_RECYCLE_BIN"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="NOT_RESTORE",
        ), patch.object(recycle_bin, "_open_recycle_bin") as opened:
            result = recycle_bin.execute("打开回收站", "")
        opened.assert_called_once_with()
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "opened_recycle_bin")

    def test_windows_open_uses_only_fixed_shell_namespace(self):
        with patch.object(recycle_bin.sys, "platform", "win32"), patch.object(
            recycle_bin.subprocess, "Popen"
        ) as popen:
            recycle_bin._open_recycle_bin()
        popen.assert_called_once_with(
            ["explorer.exe", "shell:RecycleBinFolder"],
            close_fds=True,
        )

    def test_mutating_recycle_action_is_unsupported(self):
        with patch.object(
            recycle_bin, "_plan", return_value="UNSUPPORTED"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="NOT_RESTORE",
        ):
            result = recycle_bin.execute("清空回收站", "")
        self.assertFalse(result["success"])
        self.assertTrue(result["unsupported"])

    def test_restore_requires_confirmation_with_opaque_item_id(self):
        item = {
            "id": "item-id",
            "name": "old.txt",
            "shell_path": "C:/$Recycle.Bin/recycled.txt",
            "original_location": "C:/Users/Test/Desktop",
            "date_deleted": "2026-08-16",
            "size": "12",
        }
        with patch.object(
            recycle_bin, "_plan", return_value="RESTORE_RECYCLE_ITEM"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="RESTORE_ITEM",
        ), patch.object(
            recycle_bin, "_discover_items", return_value=[item]
        ), patch.object(
            recycle_bin, "_select_item_id", return_value="item-id"
        ), patch.object(recycle_bin, "_restore_item") as restore:
            result = recycle_bin.execute("恢复 old.txt", "")
        restore.assert_not_called()
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["approval_type"], "recycle_restore")
        self.assertEqual(result["candidate_id"], "item-id")

    def test_confirmed_restore_executes_only_approved_current_item(self):
        item = {
            "id": "item-id",
            "name": "old.txt",
            "shell_path": "C:/$Recycle.Bin/recycled.txt",
            "original_location": "C:/Users/Test/Desktop",
            "date_deleted": "2026-08-16",
            "size": "12",
        }
        approval = {
            "action": "restore_recycle_item",
            "candidate_id": "item-id",
        }
        with patch.object(
            recycle_bin, "_plan"
        ) as plan, patch.object(
            recycle_bin, "_discover_items", return_value=[item]
        ), patch.object(
            recycle_bin, "_restore_item"
        ) as restore, patch.object(
            recycle_bin, "_restore_completed", return_value=True
        ):
            result = recycle_bin.execute(
                "恢复 old.txt", "", approval=approval
            )
        restore.assert_called_once_with(item)
        plan.assert_not_called()
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "restored_recycle_item")

    def test_restore_uses_shell_undelete_canonical_verb(self):
        item = {
            "shell_path": "C:/$Recycle.Bin/recycled.txt",
        }
        completed = type(
            "Completed", (), {"returncode": 0, "stderr": ""}
        )()
        with patch.object(
            recycle_bin.sys, "platform", "win32"
        ), patch.object(
            recycle_bin.subprocess, "run", return_value=completed
        ) as run:
            recycle_bin._restore_item(item)
        command = run.call_args.args[0]
        self.assertIn("InvokeVerb('undelete')", command[-1])
        self.assertNotIn("InvokeVerb('RESTORE')", command[-1])
        self.assertEqual(
            run.call_args.kwargs["env"]["BEKKI_RECYCLE_ITEM_PATH"],
            item["shell_path"],
        )

    def test_restore_disagreement_is_decided_by_independent_arbiter(self):
        item = {
            "id": "item-id",
            "name": "version_info",
            "shell_path": "C:/$Recycle.Bin/version_info",
            "original_location": "C:/Users/Main/Downloads",
            "date_deleted": "2026-08-17",
            "size": "838",
        }
        with patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="RESTORE_ITEM",
        ), patch.object(
            recycle_bin, "_plan", return_value="LIST_RECYCLE_BIN"
        ) as broad_plan, patch.object(
            recycle_bin,
            "_arbitrate_action",
            return_value="RESTORE_RECYCLE_ITEM",
        ) as arbiter, patch.object(
            recycle_bin, "_discover_items", return_value=[item]
        ), patch.object(
            recycle_bin, "_select_item_id", return_value="item-id"
        ):
            result = recycle_bin.execute(
                "恢复回收站里的 version_info", ""
            )
        broad_plan.assert_called_once()
        arbiter.assert_called_once()
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["candidate_id"], "item-id")

    def test_old_chat_cannot_turn_open_window_into_restore(self):
        stale_context = (
            "User: 恢复回收站里的旧文件。\n"
            "Assistant: 之前还讨论了一个无关人物归属。"
        )
        with patch.object(
            recycle_bin, "_plan", return_value="OPEN_RECYCLE_BIN"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="RESTORE_ITEM",
        ), patch.object(
            recycle_bin,
            "_arbitrate_action",
            return_value="OPEN_RECYCLE_BIN",
        ) as arbiter, patch.object(
            recycle_bin, "_open_recycle_bin"
        ) as opened, patch.object(
            recycle_bin, "_discover_items"
        ) as discover:
            result = recycle_bin.execute("打开回收站", stale_context)

        arbiter.assert_called_once_with(
            "打开回收站",
            stale_context,
            "OPEN_RECYCLE_BIN",
            "RESTORE_ITEM",
        )
        opened.assert_called_once_with()
        discover.assert_not_called()
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "opened_recycle_bin")

    def test_invalid_disagreement_arbitration_fails_safe_to_clarify(self):
        with patch.object(
            recycle_bin, "_plan", return_value="OPEN_RECYCLE_BIN"
        ), patch.object(
            recycle_bin,
            "_classify_restore_intent",
            return_value="RESTORE_ITEM",
        ), patch.object(
            recycle_bin, "_arbitrate_action", return_value=""
        ), patch.object(recycle_bin, "_open_recycle_bin") as opened, patch.object(
            recycle_bin, "_discover_items"
        ) as discover:
            result = recycle_bin.execute("打开回收站", "old unrelated task")

        opened.assert_not_called()
        discover.assert_not_called()
        self.assertTrue(result["needs_clarification"])

    def test_restore_classifier_places_current_request_before_old_context(self):
        model = unittest.mock.Mock(return_value="NOT_RESTORE")
        tools_stub = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": tools_stub}):
            verdict = recycle_bin._classify_restore_intent(
                "打开回收站",
                "User: 恢复旧文件",
            )

        self.assertEqual(verdict, "NOT_RESTORE")
        prompt_input = model.call_args.args[1]
        self.assertLess(
            prompt_input.index("打开回收站"),
            prompt_input.index("恢复旧文件"),
        )


if __name__ == "__main__":
    unittest.main()
