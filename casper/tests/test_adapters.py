import unittest
from unittest.mock import patch

from casper import adapters


class AdapterRenderingTests(unittest.TestCase):
    def test_external_ai_completed_result_is_visible_and_unverified(self):
        with patch(
            "casper.external_ai.execute_explicit",
            return_value={
                "status": "COMPLETED",
                "provider": "ChatGPT Desktop",
                "outbound_prompt": "为什么猫会呼噜？",
                "answer": "可能与交流和自我安抚有关。",
                "verification_status": "UNVERIFIED_EXTERNAL_AI",
            },
        ):
            search_result, context = adapters.execute_mode(
                "帮我问 ChatGPT：为什么猫会呼噜？",
                {"response_mode": "EXTERNAL_AI_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "LOCAL_ACTION_RESULT")
        self.assertIn("我实际发送的问题", search_result["direct_reply"])
        self.assertIn("ChatGPT Desktop", search_result["direct_reply"])
        self.assertIn("尚未验证", search_result["direct_reply"])
        self.assertIn("UNVERIFIED", context)

    def test_external_ai_desktop_login_uses_existing_checkpoint_type(self):
        with patch(
            "casper.external_ai.execute_explicit",
            return_value={"status": "DESKTOP_LOGIN_REQUIRED"},
        ):
            search_result, context = adapters.execute_mode(
                "帮我问 ChatGPT 一个问题",
                {"response_mode": "EXTERNAL_AI_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertIsNone(context)
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "external_ai_login_handoff")
        self.assertEqual(pending["event"], "external_ai_desktop_login")

    def test_external_ai_desktop_timeout_is_direct_and_never_requests_retry(self):
        with patch(
            "casper.external_ai.execute_explicit",
            return_value={
                "status": "DESKTOP_RESPONSE_TIMEOUT",
                "prompt_sent": True,
            },
        ):
            search_result, context = adapters.execute_mode(
                "帮我问 ChatGPT 一个问题",
                {"response_mode": "EXTERNAL_AI_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertIsNone(context)
        self.assertIn("问题已发送", search_result["direct_reply"])
        self.assertIn("不会自动重试", search_result["direct_reply"])

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

    def test_installed_fm_tactic_has_deterministic_reply(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(
            search_result["direct_reply"],
            "已安装 winner.fmf 到 Football Manager 2026 tactics。",
        )

    def test_content_manifest_never_claims_download_or_install(self):
        action_result = {
            "success": True,
            "completed": False,
            "action": "prepared_content_installation_manifest",
            "manifest": {
                "artifact_name": "Community Mod",
                "target_app": "Example Game",
            },
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找并安装 mod",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        reply = search_result["direct_reply"]
        self.assertIn("Community Mod", reply)
        self.assertIn("尚未下载或安装", reply)

    def test_learned_procedure_becomes_continue_checkpoint(self):
        action_result = {
            "success": True,
            "completed": False,
            "action": "learned_content_skill_candidate",
            "requires_continuation": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "destination_name": "Football Manager 2026 tactics",
            "original_request": "找战术并安装",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "content_learning_continue")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"], "candidate-id"
        )

    def test_content_browser_verification_becomes_handoff(self):
        action_result = {
            "success": False,
            "completed": False,
            "protected_event": "captcha",
            "reason": "verification",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "网上找并安装 mod",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        self.assertEqual(
            search_result["pending_approval"]["handoff_type"],
            "browser_handoff",
        )

    def test_second_stage_browser_handoff_preserves_skill_id(self):
        action_result = {
            "success": False,
            "completed": False,
            "protected_event": "captcha",
            "resume_skill_id": "candidate-id",
            "reason": "verification",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "继续安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "content_browser_handoff")
        self.assertEqual(
            pending["approval_payload"]["skill_id"], "candidate-id"
        )

    def test_first_success_waits_for_user_before_skill_commit(self):
        action_result = {
            "success": True,
            "completed": True,
            "action": "content_installation_awaiting_user_verification",
            "requires_user_verification": True,
            "skill_candidate_id": "candidate-id",
            "target_app": "Football Manager 2026",
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找并安装战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["handoff_type"], "skill_user_verification")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"], "candidate-id"
        )

    def test_device_clarification_is_rendered_without_model_rewrite(self):
        action_result = {
            "success": False,
            "needs_clarification": True,
            "clarification": "搜索结果与目标游戏内容无关。",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(
            search_result["direct_reply"],
            "搜索结果与目标游戏内容无关。",
        )

    def test_retryable_content_failure_restores_continue_checkpoint(self):
        action_result = {
            "success": False,
            "needs_clarification": True,
            "clarification": "没有找到下载链接。",
            "content_installation_retry_available": True,
            "resume_skill_id": "candidate-id",
            "target_app": "Football Manager 26",
            "destination_name": "Football Manager 26 tactics",
            "original_request": "找战术并安装",
        }
        with patch(
            "casper.device_actions.execute_user_request",
            return_value=action_result,
        ):
            search_result, _context = adapters.execute_mode(
                "找战术并安装",
                {"response_mode": "DEVICE_ACTION"},
                {},
                "",
                lambda _message: None,
            )
        self.assertEqual(search_result["status"], "HUMAN_HANDOFF")
        pending = search_result["pending_approval"]
        self.assertEqual(pending["event"], "content_installation_retry")
        self.assertEqual(
            pending["approval_payload"]["skill_candidate_id"],
            "candidate-id",
        )


if __name__ == "__main__":
    unittest.main()
