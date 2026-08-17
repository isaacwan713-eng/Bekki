import unittest
from unittest.mock import patch

from casper import recycle_bin


class RecycleBinTests(unittest.TestCase):
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

    def test_focused_restore_intent_overrides_wrong_list_plan(self):
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
            recycle_bin, "_plan"
        ) as broad_plan, patch.object(
            recycle_bin, "_discover_items", return_value=[item]
        ), patch.object(
            recycle_bin, "_select_item_id", return_value="item-id"
        ):
            result = recycle_bin.execute(
                "恢复回收站里的 version_info", ""
            )
        broad_plan.assert_not_called()
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["candidate_id"], "item-id")


if __name__ == "__main__":
    unittest.main()
