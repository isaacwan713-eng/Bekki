import os
from pathlib import Path
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
            ), patch.object(
                file_actions,
                "discover_search_roots",
                return_value=[self._root(folder)],
            ), patch.object(file_actions, "_plan", return_value=plan):
                result = file_actions.execute("打开文件", "")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_exact_recursive_search_returns_only_observed_path(self):
        with tempfile.TemporaryDirectory() as folder:
            nested = os.path.join(folder, "Projects", "Bekki")
            os.makedirs(nested)
            expected_path = os.path.join(nested, "test.txt")
            Path(expected_path).write_text("real", encoding="utf-8")
            Path(os.path.join(nested, "test.txt.bak")).write_text(
                "not exact", encoding="utf-8"
            )
            plan = {
                "action": "SEARCH_FILES",
                "query": "test.txt",
                "match_mode": "EXACT_NAME",
                "target_kind": "FILE",
            }
            with patch.object(
                file_actions,
                "discover_user_roots",
                return_value=[self._root(folder)],
            ), patch.object(
                file_actions, "discover_entries", return_value=[]
            ), patch.object(
                file_actions,
                "discover_search_roots",
                return_value=[self._root(folder)],
            ), patch.object(file_actions, "_plan", return_value=plan):
                result = file_actions.execute(
                    "帮我在电脑里查找名为 test.txt 的文件", ""
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "searched_files")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["path"], expected_path)
        self.assertNotIn("test.txt.bak", str(result["matches"]))

    def test_search_rejects_paths_and_globs_before_filesystem_walk(self):
        plan = {
            "action": "SEARCH_FILES",
            "query": "../test*.txt",
            "match_mode": "EXACT_NAME",
            "target_kind": "FILE",
        }
        with patch.object(
            file_actions,
            "discover_user_roots",
            return_value=[self._root("C:/Users/Test/Desktop")],
        ), patch.object(
            file_actions, "discover_entries", return_value=[]
        ), patch.object(
            file_actions,
            "discover_search_roots",
            return_value=[self._root("C:/Users/Test")],
        ), patch.object(
            file_actions, "_plan", return_value=plan
        ), patch.object(
            file_actions, "search_user_files"
        ) as search:
            result = file_actions.execute("查找 ../test*.txt", "")

        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])
        search.assert_not_called()

    def test_reliable_gate_constrains_named_file_request_to_search(self):
        calls = []
        outputs = [
            "SEARCH_FILES",
            {
                "action": "SEARCH_FILES",
                "root_id": None,
                "candidate_id": None,
                "folder_name": None,
                "query": "bekki_search_test.txt",
                "match_mode": "EXACT_NAME",
                "target_kind": "FILE",
                "reason": "Locate one exact filename.",
            },
        ]

        def run_ai_prompt(*args, **kwargs):
            calls.append((args, kwargs))
            return outputs.pop(0)

        fake_tools = types.SimpleNamespace(
            run_ai_prompt=run_ai_prompt,
            unload_model=lambda *_args, **_kwargs: None,
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            plan = file_actions._plan(
                "帮我在电脑里查找名为 bekki_search_test.txt 的文件",
                "",
                [],
                [],
            )

        self.assertEqual(plan["action"], "SEARCH_FILES")
        self.assertEqual(calls[0][1]["model_name"], "gemma3:12b")
        self.assertEqual(calls[1][1]["model_name"], "gemma3:4b")
        action_enum = calls[1][1]["json_schema"]["properties"]["action"]["enum"]
        self.assertEqual(action_enum, ["SEARCH_FILES"])

    def test_file_prompt_has_no_list_folder_shape_anchor(self):
        prompt_path = (
            Path(file_actions.__file__).resolve().parents[1]
            / "prompts"
            / "casper_file_action.txt"
        )
        prompt = prompt_path.read_text(encoding="utf-8")
        self.assertNotIn('{"action":"LIST_FOLDER"', prompt)
        self.assertIn("is SEARCH_FILES", prompt)


if __name__ == "__main__":
    unittest.main()
