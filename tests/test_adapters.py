import unittest
from unittest.mock import patch

from casper import adapters


class AdapterRenderingTests(unittest.TestCase):
    def test_folder_items_are_rendered_once(self):
        result = {
            "folder": "Downloads",
            "items": [
                {"name": "installer.exe", "kind": "file"},
                {"name": "Bekki_Update.zip", "kind": "file"},
                {"name": "Photos", "kind": "folder"},
            ],
        }
        reply = adapters._render_listed_folder(result)
        self.assertIn("Downloads 文件夹里有 3 项", reply)
        self.assertEqual(reply.count("installer.exe"), 1)
        self.assertEqual(reply.count("Bekki_Update.zip"), 1)
        self.assertEqual(reply.count("Photos"), 1)

    def test_empty_folder_has_compact_direct_reply(self):
        reply = adapters._render_listed_folder(
            {"folder": "Downloads", "items": []}
        )
        self.assertEqual(reply, "Downloads 文件夹目前是空的。")

    def test_recycle_bin_items_are_rendered_once(self):
        reply = adapters._render_recycle_bin(
            {
                "items": [
                    {
                        "name": "old.txt",
                        "original_location": "C:/Users/Test/Desktop",
                        "date_deleted": "2026-08-16",
                    },
                    {"name": "photo.png"},
                ],
                "truncated": False,
            }
        )
        self.assertIn("回收站里有 2 项", reply)
        self.assertEqual(reply.count("old.txt"), 1)
        self.assertEqual(reply.count("photo.png"), 1)

    def test_recycle_restore_handoff_preserves_opaque_approval(self):
        action_result = {
            "success": False,
            "requires_approval": True,
            "approval_type": "recycle_restore",
            "action": "restore_recycle_item",
            "candidate_id": "opaque-item-id",
            "name": "old.txt",
            "original_location": "C:/Users/Test/Desktop",
        }
        plan = {"response_mode": "DEVICE_ACTION"}
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "恢复 old.txt", plan, {}, "", lambda _message: None
            )
        pending = search_result["pending_approval"]
        self.assertEqual(pending["event"], "recycle_restore")
        self.assertEqual(
            pending["approval_payload"]["candidate_id"],
            "opaque-item-id",
        )

    def test_window_control_direct_reply_cannot_claim_file_restore(self):
        reply = adapters._render_window_control(
            {
                "action": "window_control_completed",
                "control": "FOCUS_WINDOW",
                "window": "Microsoft Edge",
            }
        )
        self.assertEqual(reply, "已切换到 Microsoft Edge。")
        self.assertNotIn("恢复文件", reply)


if __name__ == "__main__":
    unittest.main()
