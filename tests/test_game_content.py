import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from casper import game_content


class GameContentTests(unittest.TestCase):
    def _layout(self, root):
        documents = Path(root) / "Documents"
        downloads = Path(root) / "Downloads"
        game_root = (
            documents / "Sports Interactive" / "Football Manager 26"
        )
        game_root.mkdir(parents=True)
        downloads.mkdir()
        return documents, downloads, game_root

    def test_discovers_real_fmf_and_existing_fm26_data_root(self):
        with tempfile.TemporaryDirectory() as root:
            documents, downloads, game_root = self._layout(root)
            tactic = downloads / "best tactic.fmf"
            tactic.write_bytes(b"FM tactic data")
            with patch.object(
                game_content,
                "_candidate_user_folders",
                return_value=[documents, downloads],
            ):
                sources = game_content.discover_fm_tactic_sources()
                destinations = game_content.discover_fm_tactic_destinations()
        self.assertEqual([item["name"] for item in sources], ["best tactic.fmf"])
        self.assertEqual(len(destinations), 1)
        self.assertTrue(
            destinations[0]["path"].endswith(
                os.path.join("Football Manager 26", "tactics")
            )
        )
        self.assertEqual(destinations[0]["name"], "Football Manager 26 tactics")

    def test_enumerates_existing_game_roots_without_guessing_one_title(self):
        with tempfile.TemporaryDirectory() as root:
            documents = Path(root) / "Documents"
            publisher = documents / "Sports Interactive"
            (publisher / "Football Manager 24").mkdir(parents=True)
            (publisher / "Football Manager 26").mkdir()
            (documents / "Unrelated Game").mkdir()
            with patch.object(
                game_content,
                "_candidate_user_folders",
                return_value=[documents],
            ):
                destinations = game_content.discover_fm_tactic_destinations()
        self.assertEqual(
            [item["name"] for item in destinations],
            ["Football Manager 24 tactics", "Football Manager 26 tactics"],
        )

    def test_windows_configured_documents_is_added_to_bounded_roots(self):
        with tempfile.TemporaryDirectory() as root:
            configured = Path(root) / "Redirected Documents"
            with patch.object(
                game_content,
                "_windows_personal_documents",
                return_value=configured,
            ), patch.dict(
                game_content.os.environ,
                {"USERPROFILE": str(Path(root) / "Profile")},
                clear=False,
            ):
                folders = game_content._candidate_user_folders()
        normalized = {
            os.path.normcase(os.path.abspath(str(folder))) for folder in folders
        }
        self.assertIn(
            os.path.normcase(os.path.abspath(str(configured))), normalized
        )

    def test_ai_selected_tactic_is_copied_and_verified(self):
        with tempfile.TemporaryDirectory() as root:
            documents, downloads, game_root = self._layout(root)
            source_path = downloads / "winner.fmf"
            source_path.write_bytes(b"valid tactic")
            source = {
                "id": "source-id",
                "name": source_path.name,
                "path": str(source_path),
                "size": source_path.stat().st_size,
                "kind": "fm_tactic_source",
            }
            destination = {
                "id": "destination-id",
                "name": "Football Manager 2026 tactics",
                "path": str(game_root / "tactics"),
                "game_root": str(game_root),
                "kind": "fm_tactic_destination",
            }
            with patch.object(
                game_content, "discover_fm_tactic_sources", return_value=[source]
            ), patch.object(
                game_content,
                "discover_fm_tactic_destinations",
                return_value=[destination],
            ), patch.object(
                game_content,
                "_select_install",
                return_value=("source-id", "destination-id"),
            ):
                result = game_content.execute("安装刚下载的战术", "")
            installed = game_root / "tactics" / "winner.fmf"
            self.assertTrue(installed.is_file())
            self.assertEqual(installed.read_bytes(), b"valid tactic")
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "installed_fm_tactic")

    def test_executable_disguised_as_fmf_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "bad.fmf"
            path.write_bytes(b"MZ" + b"payload")
            with self.assertRaises(OSError):
                game_content._validate_source({"path": str(path)})

    def test_invented_ai_id_cannot_install_anything(self):
        source = {
            "id": "source-id",
            "name": "safe.fmf",
            "path": "unused",
            "size": 12,
        }
        destination = {
            "id": "destination-id",
            "name": "FM26 tactics",
            "path": "unused",
            "game_root": "unused",
        }
        with patch.object(
            game_content, "discover_fm_tactic_sources", return_value=[source]
        ), patch.object(
            game_content,
            "discover_fm_tactic_destinations",
            return_value=[destination],
        ), patch.object(
            game_content,
            "_select_install",
            return_value=("invented", "destination-id"),
        ):
            result = game_content.execute("安装战术", "")
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_learned_destination_is_revalidated_before_install(self):
        with tempfile.TemporaryDirectory() as root:
            game_root = Path(root) / "Football Manager 2026"
            destination_path = game_root / "tactics"
            game_root.mkdir()
            source_path = Path(root) / "downloaded.fmf"
            source_path.write_bytes(b"valid tactic")
            destination = {
                "id": "destination-id",
                "name": "Football Manager 2026 tactics",
                "path": str(destination_path),
                "game_root": str(game_root),
            }
            with patch.object(
                game_content,
                "discover_fm_tactic_destinations",
                return_value=[destination],
            ):
                result = game_content.install_verified_fm_tactic(
                    source_path, destination_path
                )
            self.assertTrue((destination_path / "downloaded.fmf").is_file())
        self.assertTrue(result["success"])

    def test_changed_learned_destination_fails_closed(self):
        with patch.object(
            game_content,
            "discover_fm_tactic_destinations",
            return_value=[],
        ):
            result = game_content.install_verified_fm_tactic(
                "unused.fmf", "C:/changed/path"
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])

    def test_verified_folder_skill_revalidates_exact_destination_before_open(self):
        destination = {
            "id": "destination-id",
            "name": "Football Manager 26 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
        }
        with patch.object(
            game_content,
            "discover_fm_tactic_destinations",
            return_value=[destination],
        ), patch.object(
            game_content.sys, "platform", "win32"
        ), patch.object(
            game_content.os, "makedirs"
        ) as makedirs, patch.object(
            game_content.os, "startfile", create=True
        ) as startfile:
            result = game_content.open_verified_fm_tactic_destination(
                destination["path"]
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "opened_fm_tactic_folder")
        makedirs.assert_called_once_with(destination["path"], exist_ok=True)
        startfile.assert_called_once_with(destination["path"])

    def test_verified_folder_skill_fails_when_destination_changed(self):
        with patch.object(
            game_content,
            "discover_fm_tactic_destinations",
            return_value=[],
        ):
            result = game_content.open_verified_fm_tactic_destination(
                "C:/changed/path"
            )
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
