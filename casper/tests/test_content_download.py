from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from casper import content_download


class ContentDownloadTests(unittest.TestCase):
    def _manifest(self):
        return {
            "artifact_name": "Winning tactic",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "source_url": "https://example.test/tactic",
        }

    def _procedure(self):
        return {
            "local_adapter": "FM_TACTIC",
            "expected_file_types": [".fmf"],
            "verified_destination_path": "C:/Users/Test/Documents/FM26/tactics",
        }

    def test_downloaded_tactic_is_validated_then_installed(self):
        def activate(_url, _link_id, destination_dir):
            path = Path(destination_dir) / "winner.fmf"
            path.write_bytes(b"valid tactic")
            return {"status": "DOWNLOADED", "path": str(path)}

        installed = {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
        }
        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "OK", "links": [{"id": "link-id"}]},
        ), patch.object(
            content_download, "_select_link", return_value="link-id"
        ), patch.object(
            content_download.browser,
            "activate_page_link",
            side_effect=activate,
        ), patch.object(
            content_download.game_content,
            "install_verified_fm_tactic",
            return_value=installed,
        ) as install:
            result = content_download.execute(
                self._manifest(), self._procedure()
            )
        self.assertEqual(result, installed)
        self.assertTrue(install.called)

    def test_executable_header_is_rejected_before_install(self):
        def activate(_url, _link_id, destination_dir):
            path = Path(destination_dir) / "bad.fmf"
            path.write_bytes(b"MZpayload")
            return {"status": "DOWNLOADED", "path": str(path)}

        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "OK", "links": [{"id": "link-id"}]},
        ), patch.object(
            content_download, "_select_link", return_value="link-id"
        ), patch.object(
            content_download.browser,
            "activate_page_link",
            side_effect=activate,
        ), patch.object(
            content_download.game_content, "install_verified_fm_tactic"
        ) as install:
            result = content_download.execute(
                self._manifest(), self._procedure()
            )
        self.assertFalse(result["success"])
        install.assert_not_called()

    def test_one_download_page_navigation_is_allowed(self):
        calls = []

        def activate(url, _link_id, destination_dir):
            calls.append(url)
            if len(calls) == 1:
                return {"status": "NAVIGATED", "url": "https://example.test/download"}
            path = Path(destination_dir) / "winner.fmf"
            path.write_bytes(b"valid tactic")
            return {"status": "DOWNLOADED", "path": str(path)}

        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "OK", "links": [{"id": "link-id"}]},
        ), patch.object(
            content_download, "_select_link", return_value="link-id"
        ), patch.object(
            content_download.browser,
            "activate_page_link",
            side_effect=activate,
        ), patch.object(
            content_download.game_content,
            "install_verified_fm_tactic",
            return_value={"success": True},
        ):
            result = content_download.execute(
                self._manifest(), self._procedure()
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 2)

    def test_index_article_and_host_navigation_are_bounded_but_allowed(self):
        calls = []

        def activate(url, _link_id, destination_dir):
            calls.append(url)
            if len(calls) == 1:
                return {
                    "status": "NAVIGATED",
                    "url": "https://example.test/tactic-article",
                }
            if len(calls) == 2:
                return {
                    "status": "NAVIGATED",
                    "url": "https://media.example/file-page",
                }
            path = Path(destination_dir) / "winner.fmf"
            path.write_bytes(b"valid tactic")
            return {"status": "DOWNLOADED", "path": str(path)}

        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "OK", "links": [{"id": "link-id"}]},
        ), patch.object(
            content_download, "_select_link", return_value="link-id"
        ), patch.object(
            content_download.browser,
            "activate_page_link",
            side_effect=activate,
        ), patch.object(
            content_download.game_content,
            "install_verified_fm_tactic",
            return_value={"success": True},
        ):
            result = content_download.execute(
                self._manifest(), self._procedure()
            )
        self.assertTrue(result["success"])
        self.assertEqual(len(calls), 3)

    def test_browser_verification_preserves_resume_skill(self):
        procedure = self._procedure()
        procedure["id"] = "procedure-id"
        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "HUMAN_HANDOFF", "event": "captcha"},
        ):
            result = content_download.execute(self._manifest(), procedure)
        self.assertEqual(result["protected_event"], "captcha")
        self.assertEqual(result["resume_skill_id"], "procedure-id")

    def test_link_selection_retries_after_empty_ai_response(self):
        model = Mock(side_effect=[None, {"link_id": "artifact-link"}])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        links = [
            {
                "id": "artifact-link",
                "text": "Download Winning tactic",
                "domain": "example.test",
                "path": "/winner/download",
            }
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = content_download._select_link(
                self._manifest(), self._procedure(),
                "https://example.test/tactic", links,
            )
        self.assertEqual(selected, "artifact-link")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_download_link_retry.txt",
        )

    def test_link_selection_rejects_invented_ai_id(self):
        model = Mock(return_value={"link_id": "invented-link"})
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        links = [{"id": "real-link", "text": "Download"}]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = content_download._select_link(
                self._manifest(), self._procedure(),
                "https://example.test/tactic", links,
            )
        self.assertEqual(selected, "")
        self.assertEqual(model.call_count, 2)

    def test_new_tab_matching_selected_href_is_followed(self):
        selected = content_download.browser._select_clicked_navigation_url(
            "https://passion.example/tactic",
            "https://passion.example/tactic",
            [
                "about:blank",
                "https://media.example/file/winner.fmf/file",
            ],
            "https://media.example/file/winner.fmf/file",
        )
        self.assertEqual(
            selected, "https://media.example/file/winner.fmf/file"
        )

    def test_unrelated_popup_is_not_mistaken_for_selected_href(self):
        selected = content_download.browser._select_clicked_navigation_url(
            "https://passion.example/tactic",
            "https://passion.example/tactic",
            [
                "https://ads.example/offer",
                "https://other.example/article",
            ],
            "https://media.example/file/winner.fmf/file",
        )
        self.assertEqual(selected, "")


if __name__ == "__main__":
    unittest.main()
