import sys
import types
import unittest
from unittest.mock import Mock, patch

from casper import content_workflow


STALE_INSTALL_REQUEST = (
    "网上找一个适合曼联的强力 FM26 战术并导入电脑"
)
OPEN_FOLDER_REQUEST = "打开 FM26 战术文件夹"


class ContentContextIsolationTests(unittest.TestCase):
    def test_context_scope_accepts_only_exact_ai_enum(self):
        model = Mock(side_effect=["current_only", "CURRENT_ONLY"])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = content_workflow._classify_context_scope(
                OPEN_FOLDER_REQUEST, STALE_INSTALL_REQUEST
            )
        self.assertEqual(result, "CURRENT_ONLY")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_context_scope.txt",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_context_scope_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"], "gemma4:12b"
        )
        self.assertEqual(model.call_args_list[0].kwargs["num_predict"], 700)
        self.assertEqual(model.call_args_list[0].kwargs["num_ctx"], 4096)
        self.assertEqual(model.call_args_list[1].kwargs["num_predict"], 1400)
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 8192)

    def test_context_scope_prompts_show_complete_cross_app_folder_commands(self):
        project_root = content_workflow.__file__
        from pathlib import Path

        prompt_root = Path(project_root).resolve().parent.parent / "prompts"
        for name in (
            "casper_content_context_scope.txt",
            "casper_content_context_scope_retry.txt",
        ):
            with self.subTest(prompt=name):
                text = (prompt_root / name).read_text(encoding="utf-8")
                self.assertIn("Minecraft Java Edition", text)
                self.assertIn("Cities: Skylines II", text)
                self.assertIn("CURRENT_ONLY", text)

    def test_standalone_folder_request_never_queries_stale_pending_candidate(self):
        folder_result = {
            "success": True,
            "completed": True,
            "action": "folder_skill_awaiting_user_verification",
        }
        stale_candidate = {
            "id": "candidate-old-install",
            "status": "pending_execution",
            "skill_scope": "INSTALL_CONTENT",
            "original_request": STALE_INSTALL_REQUEST,
        }
        call_order = []

        def stage(_message, context):
            call_order.append(("stage", context))
            return "OPEN_FOLDER_ONLY"

        def verified(_message, context):
            call_order.append(("verified", context))
            return None

        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            side_effect=stage,
        ), patch(
            "casper.skill_registry.match_pending_resume",
            return_value={
                "skill": stale_candidate,
                "resume_request": STALE_INSTALL_REQUEST,
            },
        ) as pending, patch(
            "casper.skill_registry.match_verified",
            side_effect=verified,
        ), patch(
            "casper.content_learning.execute",
            return_value=folder_result,
        ) as learning, patch(
            "casper.content_research.execute"
        ) as research:
            result = content_workflow.execute(
                OPEN_FOLDER_REQUEST,
                "You: " + STALE_INSTALL_REQUEST,
                content_authorized=True,
                skill_lookup_requested=True,
            )

        self.assertEqual(result, folder_result)
        pending.assert_not_called()
        research.assert_not_called()
        self.assertEqual(call_order, [("stage", ""), ("verified", "")])
        learning.assert_called_once_with(
            OPEN_FOLDER_REQUEST,
            "",
            status_callback=None,
            requested_skill_scope="OPEN_DESTINATION_FOLDER",
        )

    def test_needs_context_retains_only_bounded_prior_context(self):
        recent_context = "discard-me:" + ("x" * 1400) + ":tail"
        expected = recent_context[-content_workflow.MAX_ISOLATED_CONTEXT_CHARS:]
        learned = {"success": True, "action": "learned"}

        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="NEEDS_CONTEXT",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ) as stage, patch(
            "casper.skill_registry.match_verified",
            return_value=None,
        ) as verified, patch(
            "casper.skill_registry.match_pending_resume"
        ) as pending, patch(
            "casper.content_learning.execute",
            return_value=learned,
        ) as learning:
            result = content_workflow.execute(
                "那就安装刚才那个",
                recent_context,
                content_authorized=True,
                skill_lookup_requested=True,
            )

        self.assertEqual(result, learned)
        stage.assert_called_once_with("那就安装刚才那个", expected)
        verified.assert_called_once_with("那就安装刚才那个", expected)
        learning.assert_called_once_with(
            "那就安装刚才那个",
            expected,
            status_callback=None,
            requested_skill_scope="INSTALL_CONTENT",
        )
        pending.assert_not_called()
        self.assertNotIn("discard-me", expected)

    def test_wrong_scope_verified_install_skill_cannot_open_folder(self):
        wrong_scope = {
            "id": "verified-install",
            "status": "verified",
            "skill_scope": "INSTALL_CONTENT",
        }
        learned = {"success": True, "action": "folder-learned"}

        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="OPEN_FOLDER_ONLY",
        ), patch(
            "casper.skill_registry.match_verified",
            return_value=wrong_scope,
        ), patch(
            "casper.content_learning.reopen_verified_folder"
        ) as reopen, patch(
            "casper.content_learning.execute",
            return_value=learned,
        ) as learning:
            result = content_workflow.execute(
                OPEN_FOLDER_REQUEST,
                STALE_INSTALL_REQUEST,
                content_authorized=True,
                skill_lookup_requested=True,
            )

        self.assertEqual(result, learned)
        reopen.assert_not_called()
        learning.assert_called_once_with(
            OPEN_FOLDER_REQUEST,
            "",
            status_callback=None,
            requested_skill_scope="OPEN_DESTINATION_FOLDER",
        )

    def test_wrong_scope_verified_folder_skill_cannot_install_content(self):
        wrong_scope = {
            "id": "verified-folder",
            "status": "verified",
            "skill_scope": "OPEN_DESTINATION_FOLDER",
        }
        learned = {"success": True, "action": "install-learning"}

        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.match_verified",
            return_value=wrong_scope,
        ), patch(
            "casper.content_research.execute"
        ) as research, patch(
            "casper.content_learning.execute",
            return_value=learned,
        ) as learning:
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "old context",
                content_authorized=True,
                skill_lookup_requested=True,
            )

        self.assertEqual(result, learned)
        research.assert_not_called()
        learning.assert_called_once_with(
            STALE_INSTALL_REQUEST,
            "",
            status_callback=None,
            requested_skill_scope="INSTALL_CONTENT",
        )

    def test_explicit_checkpoint_id_is_only_pending_resume_path(self):
        pending_skill = {
            "id": "candidate-exact",
            "status": "pending_execution",
            "skill_scope": "INSTALL_CONTENT",
            "original_request": STALE_INSTALL_REQUEST,
        }
        installed = {"success": True, "completed": True}
        call_order = []

        def stage_decision(_message, _context):
            call_order.append("stage")
            return "RESEARCH_AND_INSTALL"

        def load_exact_candidate(_candidate_id):
            call_order.append("load_pending")
            return pending_skill

        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            side_effect=stage_decision,
        ) as stage, patch(
            "casper.skill_registry.load_pending",
            side_effect=load_exact_candidate,
        ) as load_pending, patch(
            "casper.skill_registry.load_verified"
        ) as load_verified, patch(
            "casper.skill_registry.match_pending_resume"
        ) as broad_pending, patch(
            "casper.skill_registry.match_verified"
        ) as broad_verified, patch(
            "casper.content_research.execute",
            return_value=installed,
        ) as research:
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "untrusted old context",
                content_authorized=True,
                resume_skill_id="candidate-exact",
                skill_lookup_requested=True,
            )

        self.assertEqual(result, installed)
        self.assertEqual(call_order, ["stage", "load_pending"])
        stage.assert_called_once_with(STALE_INSTALL_REQUEST, "")
        load_pending.assert_called_once_with("candidate-exact")
        load_verified.assert_not_called()
        broad_pending.assert_not_called()
        broad_verified.assert_not_called()
        research.assert_called_once_with(
            STALE_INSTALL_REQUEST,
            "",
            status_callback=None,
            procedure=pending_skill,
        )

    def test_invalid_context_scope_fails_closed_before_stage_or_skills(self):
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
        ) as stage, patch(
            "casper.skill_registry.match_verified"
        ) as verified, patch(
            "casper.skill_registry.match_pending_resume"
        ) as pending:
            result = content_workflow.execute(
                OPEN_FOLDER_REQUEST,
                STALE_INSTALL_REQUEST,
                content_authorized=True,
                skill_lookup_requested=True,
            )

        self.assertFalse(result["success"])
        self.assertTrue(result["needs_clarification"])
        self.assertIn("context-scope", result["reason"])
        stage.assert_not_called()
        verified.assert_not_called()
        pending.assert_not_called()

    def test_exact_resume_context_failure_preserves_same_candidate_id(self):
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="",
        ), patch(
            "casper.skill_registry.load_pending"
        ) as load_pending, patch(
            "casper.skill_registry.load_verified"
        ) as load_verified:
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "untrusted old context",
                content_authorized=True,
                resume_skill_id="candidate-exact",
            )

        self.assertTrue(result["needs_clarification"])
        self.assertTrue(result["content_installation_retry_available"])
        self.assertEqual(result["resume_skill_id"], "candidate-exact")
        self.assertEqual(result["original_request"], STALE_INSTALL_REQUEST)
        load_pending.assert_not_called()
        load_verified.assert_not_called()

    def test_exact_resume_stage_failure_preserves_same_candidate_id(self):
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="",
        ), patch(
            "casper.skill_registry.load_pending"
        ) as load_pending:
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "",
                content_authorized=True,
                resume_skill_id="candidate-exact",
            )

        self.assertTrue(result["content_installation_retry_available"])
        self.assertEqual(result["resume_skill_id"], "candidate-exact")
        load_pending.assert_not_called()

    def test_exact_resume_missing_candidate_is_terminal(self):
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="RESEARCH_AND_INSTALL",
        ), patch(
            "casper.skill_registry.load_pending", return_value=None
        ), patch(
            "casper.skill_registry.load_verified", return_value=None
        ):
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "",
                content_authorized=True,
                resume_skill_id="candidate-missing",
            )

        self.assertTrue(result["exact_resume_terminal"])
        self.assertEqual(result["resume_skill_id"], "candidate-missing")
        self.assertNotIn("content_installation_retry_available", result)

    def test_exact_resume_stage_mismatch_keeps_pending_install_candidate(self):
        pending_skill = {
            "id": "candidate-exact",
            "status": "pending_execution",
            "skill_scope": "INSTALL_CONTENT",
            "target_app": "Football Manager 2026",
            "destination_name": "Football Manager 2026 tactics",
            "original_request": STALE_INSTALL_REQUEST,
        }
        with patch.object(
            content_workflow,
            "_classify_context_scope",
            return_value="CURRENT_ONLY",
        ), patch.object(
            content_workflow,
            "_classify_authorized_stage",
            return_value="OPEN_FOLDER_ONLY",
        ), patch(
            "casper.skill_registry.load_pending", return_value=pending_skill
        ), patch(
            "casper.skill_registry.load_verified", return_value=None
        ):
            result = content_workflow.execute(
                STALE_INSTALL_REQUEST,
                "",
                content_authorized=True,
                resume_skill_id="candidate-exact",
            )

        self.assertTrue(result["content_installation_retry_available"])
        self.assertEqual(result["resume_skill_id"], "candidate-exact")
        self.assertFalse(result.get("exact_resume_terminal", False))


if __name__ == "__main__":
    unittest.main()
