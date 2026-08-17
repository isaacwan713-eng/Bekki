import os
import tempfile
import unittest
from unittest.mock import patch
import sys
import types

from casper import file_actions


class FileActionTests(unittest.TestCase):
    def _root(self, path):
        return {
            "id": "root-id",
            "name": "Desktop",
            "path": path,
            "kind": "user_root",
        }

    def test_lists_only_selected_bounded_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(folder)
            entries = [
                {
                    "id": "entry-id",
                    "name": "notes.txt",
                    "path": os.path.join(folder, "notes.txt"),
                    "kind": "file",
                    "root_id": "root-id",
                }
            ]
            plan = {
                "action": "LIST_FOLDER",
                "root_id": "root-id",
                "candidate_id": None,
            }
            with patch.object(
                file_actions, "discover_user_roots", return_value=[root]
            ), patch.object(
                file_actions, "discover_entries", return_value=entries
            ), patch.object(
                file_actions, "_plan", return_value=plan
            ), patch.object(
                file_actions, "_select_root_id", return_value="root-id"
            ):
                result = file_actions.execute("桌面有什么？", "")
        self.assertTrue(result["success"])
        self.assertEqual(result["folder"], "Desktop")
        self.assertEqual(result["items"][0]["name"], "notes.txt")

    def test_creates_one_valid_direct_child_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(folder)
            plan = {
                "action": "CREATE_FOLDER",
                "root_id": "root-id",
                "folder_name": "Tax 2026",
            }
            with patch.object(
                file_actions, "discover_user_roots", return_value=[root]
            ), patch.object(
                file_actions, "discover_entries", return_value=[]
            ), patch.object(
                file_actions, "_plan", return_value=plan
            ), patch.object(
                file_actions, "_select_root_id", return_value="root-id"
            ):
                result = file_actions.execute("创建报税文件夹", "")
            self.assertTrue(os.path.isdir(os.path.join(folder, "Tax 2026")))
        self.assertTrue(result["success"])

    def test_rejects_traversal_folder_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(folder)
            plan = {
                "action": "CREATE_FOLDER",
                "root_id": "root-id",
                "folder_name": "../outside",
            }
            with patch.object(
                file_actions, "discover_user_roots", return_value=[root]
            ), patch.object(
                file_actions, "discover_entries", return_value=[]
            ), patch.object(
                file_actions, "_plan", return_value=plan
            ), patch.object(
                file_actions, "_select_root_id", return_value="root-id"
            ):
                result = file_actions.execute("创建文件夹", "")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_focused_root_selector_overrides_wrong_desktop_plan(self):
        with tempfile.TemporaryDirectory() as desktop, tempfile.TemporaryDirectory() as downloads:
            roots = [
                self._root(desktop),
                {
                    "id": "downloads-id",
                    "name": "Downloads",
                    "path": downloads,
                    "kind": "user_root",
                },
            ]
            entries = [{
                "id": "download-file",
                "name": "installer.exe",
                "path": os.path.join(downloads, "installer.exe"),
                "kind": "file",
                "root_id": "downloads-id",
            }]
            wrong_plan = {
                "action": "LIST_FOLDER",
                "root_id": "root-id",
            }
            with patch.object(
                file_actions, "discover_user_roots", return_value=roots
            ), patch.object(
                file_actions, "discover_entries", return_value=entries
            ), patch.object(
                file_actions, "_plan", return_value=wrong_plan
            ), patch.object(
                file_actions,
                "_select_root_id",
                return_value="downloads-id",
            ):
                result = file_actions.execute(
                    "Downloads 文件夹里有什么？", ""
                )
        self.assertTrue(result["success"])
        self.assertEqual(result["folder"], "Downloads")
        self.assertEqual(result["items"][0]["name"], "installer.exe")

    def test_root_selector_does_not_receive_upstream_proposed_id(self):
        captured = {}

        def run_ai_prompt(_prompt, input_text, **_kwargs):
            captured["input"] = input_text
            return "downloads-id"

        fake_tools = types.SimpleNamespace(run_ai_prompt=run_ai_prompt)
        roots = [
            {
                "id": "desktop-id",
                "name": "Desktop",
                "path": "C:/Users/Test/Desktop",
                "kind": "user_root",
            },
            {
                "id": "downloads-id",
                "name": "Downloads",
                "path": "C:/Users/Test/Downloads",
                "kind": "user_root",
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = file_actions._select_root_id(
                "Downloads 文件夹里有什么？",
                "",
                roots,
                proposed_root_id="wrong-upstream-id",
            )
        self.assertEqual(selected, "downloads-id")
        self.assertNotIn("wrong-upstream-id", captured["input"])

    def test_invented_path_id_is_never_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(folder)
            plan = {
                "action": "OPEN_PATH",
                "candidate_id": "invented-id",
            }
            with patch.object(
                file_actions, "discover_user_roots", return_value=[root]
            ), patch.object(
                file_actions, "discover_entries", return_value=[]
            ), patch.object(file_actions, "_plan", return_value=plan):
                result = file_actions.execute("打开文件", "")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
