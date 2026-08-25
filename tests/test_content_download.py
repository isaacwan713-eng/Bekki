from pathlib import Path
import json
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
            "skill_scope": "INSTALL_CONTENT",
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

    def test_folder_skill_scope_cannot_enter_download_executor(self):
        procedure = self._procedure()
        procedure["skill_scope"] = "OPEN_DESTINATION_FOLDER"
        with patch.object(content_download.browser, "list_page_links") as links:
            result = content_download.execute(self._manifest(), procedure)
        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])
        links.assert_not_called()

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

    def test_ai_null_link_is_terminal_and_triggers_no_forced_guess(self):
        model = Mock(return_value={"link_id": None, "reason": "No exact link"})
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        links = [{"id": "generic", "text": "Resources"}]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = content_download._select_link(
                self._manifest(),
                self._procedure(),
                "https://example.test/index",
                links,
            )
        self.assertEqual(selected, "")
        self.assertEqual(model.call_count, 1)

    def test_rejected_link_id_is_removed_before_ai_reselection(self):
        model = Mock(
            side_effect=[
                {"link_id": "self-link", "reason": "invalid retry"},
                {"link_id": "download-link", "reason": "download"},
            ]
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        links = [
            {
                "id": "self-link",
                "text": "Winning tactic",
                "target_relation": "same_document",
                "download_attribute": False,
            },
            {
                "id": "download-link",
                "text": "Download Now",
                "target_relation": "different_document",
                "download_attribute": False,
            },
        ]
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = content_download._select_link(
                self._manifest(),
                self._procedure(),
                "https://example.test/tactic?id=13860",
                links,
                rejected_link_ids={"self-link"},
            )
        self.assertEqual(selected, "download-link")
        self.assertEqual(model.call_count, 2)
        for call in model.call_args_list:
            payload = json.loads(call.args[1])
            self.assertEqual(
                payload["structurally_rejected_link_ids"], ["self-link"]
            )
            self.assertEqual(
                [
                    item["id"]
                    for item in payload["untrusted_link_catalog"]
                ],
                ["download-link"],
            )

    def test_ai_generates_recovery_query_and_selects_exact_browser_result(self):
        exact_url = "https://example.test/dedicated-winning-tactic"
        source_id = content_download._recovery_source_id(exact_url)
        model = Mock(
            side_effect=[
                {"query": "Winning tactic Football Manager 2026 download"},
                {"source_id": source_id, "reason": "Exact artifact page"},
            ]
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        discovery = {
            "status": "OK",
            "results": [{
                "title": "Winning tactic for Football Manager 2026",
                "description": "Dedicated download page",
                "domain": "example.test",
                "url": exact_url,
            }],
        }
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            content_download.browser,
            "discover_web",
            return_value=discovery,
        ) as discover, patch.object(
            content_download.browser,
            "list_page_links",
            return_value={
                "status": "OK",
                "page_url": exact_url,
                "links": [{"id": "download"}],
            },
        ):
            recovered = content_download._recover_artifact_source(
                self._manifest(),
                self._procedure(),
                "https://example.test/index",
            )
        self.assertEqual(recovered, {"status": "OK", "url": exact_url})
        self.assertEqual(
            discover.call_args.args[0],
            "Winning tactic Football Manager 2026 download",
        )
        self.assertTrue(discover.call_args.kwargs["multi_engine"])

    def test_recovery_rejects_result_redirecting_to_original_index(self):
        index_url = "https://example.test/tactics-index"
        redirect_alias = "http://www.example.test/tactics-index?utm_source=search"
        good_url = "https://publisher.test/dedicated-winning-tactic"
        bad_result_url = "https://search-alias.test/result-one"
        bad_id = content_download._recovery_source_id(bad_result_url)
        good_id = content_download._recovery_source_id(good_url)
        model = Mock(
            side_effect=[
                {"query": "Winning tactic Football Manager 2026 download"},
                {"source_id": bad_id, "reason": "Title match"},
                {"source_id": good_id, "reason": "Dedicated page"},
            ]
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        discovery = {
            "status": "OK",
            "results": [
                {
                    "title": "Winning tactic",
                    "description": "Search alias",
                    "domain": "search-alias.test",
                    "url": bad_result_url,
                },
                {
                    "title": "Winning tactic dedicated download",
                    "description": "Publisher article",
                    "domain": "publisher.test",
                    "url": good_url,
                },
            ],
        }
        with patch.dict(sys.modules, {"tools": fake_tools}), patch.object(
            content_download.browser,
            "discover_web",
            return_value=discovery,
        ), patch.object(
            content_download.browser,
            "list_page_links",
            side_effect=[
                {"status": "OK", "page_url": redirect_alias, "links": []},
                {"status": "OK", "page_url": good_url, "links": []},
            ],
        ):
            recovered = content_download._recover_artifact_source(
                self._manifest(), self._procedure(), index_url
            )
        self.assertEqual(recovered, {"status": "OK", "url": good_url})
        self.assertEqual(model.call_count, 3)
        second_payload = json.loads(model.call_args_list[2].args[1])
        self.assertIn(
            bad_id,
            second_payload["structurally_rejected_source_ids"],
        )
        self.assertNotIn(
            bad_id,
            [
                item["id"]
                for item in second_payload["untrusted_search_result_catalog"]
            ],
        )

    def test_index_without_exact_link_recovers_before_three_hop_budget(self):
        dedicated_url = "https://example.test/dedicated-tactic"

        def activate(_url, _link_id, destination_dir):
            path = Path(destination_dir) / "winner.fmf"
            path.write_bytes(b"valid tactic")
            return {"status": "DOWNLOADED", "path": str(path)}

        with patch.object(
            content_download.browser,
            "list_page_links",
            return_value={"status": "OK", "links": [{"id": "link-id"}]},
        ), patch.object(
            content_download,
            "_select_link",
            side_effect=["", "link-id"],
        ) as select, patch.object(
            content_download,
            "_recover_artifact_source",
            return_value={"status": "OK", "url": dedicated_url},
        ) as recover, patch.object(
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
        recover.assert_called_once()
        self.assertEqual(select.call_args_list[1].args[2], dedicated_url)

    def test_structural_self_link_is_rejected_then_ai_reselects_same_page(self):
        dedicated_url = "https://example.test/tactics?id=13860"
        manifest = self._manifest()
        manifest["source_url"] = dedicated_url
        selected_ids = []

        def activate(_url, link_id, destination_dir):
            selected_ids.append(link_id)
            if link_id == "self-link":
                return {"status": "STRUCTURAL_NOOP", "url": dedicated_url}
            path = Path(destination_dir) / "winner.fmf"
            path.write_bytes(b"valid tactic")
            return {"status": "DOWNLOADED", "path": str(path)}

        catalog = {
            "status": "OK",
            "page_url": dedicated_url,
            "links": [
                {"id": "self-link", "target_relation": "same_document"},
                {"id": "download-link", "target_relation": "different_document"},
            ],
        }
        with patch.object(
            content_download.browser, "list_page_links", return_value=catalog
        ), patch.object(
            content_download,
            "_select_link",
            side_effect=["self-link", "download-link"],
        ) as select, patch.object(
            content_download.browser,
            "activate_page_link",
            side_effect=activate,
        ), patch.object(
            content_download.game_content,
            "install_verified_fm_tactic",
            return_value={"success": True},
        ):
            result = content_download.execute(manifest, self._procedure())
        self.assertTrue(result["success"])
        self.assertEqual(selected_ids, ["self-link", "download-link"])
        self.assertIn(
            "self-link",
            select.call_args_list[1].kwargs["rejected_link_ids"],
        )

    def test_browser_document_identity_preserves_query_and_ignores_fragment(self):
        base = "https://www.fmscout.com/c-fm26-tactics.html"
        dedicated = base + "?id=13860"
        fragment = base + "#the-ultimate-tactic"
        self.assertNotEqual(
            content_download.browser._document_url_key(base),
            content_download.browser._document_url_key(dedicated),
        )
        self.assertEqual(
            content_download.browser._document_url_key(base),
            content_download.browser._document_url_key(fragment),
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
