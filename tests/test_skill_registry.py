import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from casper import skill_registry


class SkillRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = self.temporary.name
        self.paths = patch.multiple(
            skill_registry,
            SKILLS_FILE=os.path.join(root, "skills.json"),
            PENDING_FILE=os.path.join(root, "pending.json"),
            INVALIDATED_FILE=os.path.join(root, "invalidated.json"),
            RUNS_FILE=os.path.join(root, "runs.jsonl"),
        )
        self.paths.start()

    def tearDown(self):
        self.paths.stop()
        self.temporary.cleanup()

    def _candidate(
        self,
        original_request="Find a Manchester United tactic and install it",
    ):
        return skill_registry.create_pending(
            {
                "capability": "game_content.install",
                "skill_scope": "INSTALL_CONTENT",
                "intent_summary": "Install Football Manager tactics",
                "target_app": "Football Manager 2026",
                "content_kind": "tactic",
                "parameters": ["team_or_play_style", "requested_tactic"],
                "expected_file_types": [".fmf"],
                "destination_hints": ["FM tactics folder"],
                "installation_steps": ["Place the tactic file"],
                "post_install_steps": ["Load it in FM"],
                "source_ids": ["source-id"],
                "source_urls": ["https://example.test/guide"],
                "local_adapter": "FM_TACTIC",
            },
            {
                "id": "destination-id",
                "name": "Football Manager 2026 tactics",
                "path": os.path.join(self.temporary.name, "FM26", "tactics"),
                "kind": "fm_tactic_destination",
            },
            original_request,
        )

    def test_learned_candidate_is_not_a_verified_skill(self):
        candidate = self._candidate()
        self.assertIsNotNone(skill_registry.load_pending(candidate["id"]))
        self.assertIsNone(skill_registry.load_verified(candidate["id"]))
        self.assertEqual(skill_registry._load_list(skill_registry.SKILLS_FILE), [])

    def test_candidate_cannot_commit_before_machine_and_user_verification(self):
        candidate = self._candidate()
        committed = skill_registry.commit_verified(candidate["id"], "成功了")
        self.assertIsNone(committed)
        self.assertEqual(skill_registry._load_list(skill_registry.SKILLS_FILE), [])

    def test_successful_execution_then_user_acceptance_commits_skill(self):
        candidate = self._candidate()
        marked = skill_registry.mark_execution_success(
            candidate["id"],
            {
                "success": True,
                "completed": True,
                "action": "installed_fm_tactic",
                "name": "winner.fmf",
                "destination": "Football Manager 2026 tactics",
            },
        )
        self.assertEqual(marked["status"], "pending_user_verification")
        committed = skill_registry.commit_verified(candidate["id"], "看到了")
        self.assertEqual(committed["status"], "verified")
        self.assertTrue(committed["user_verified"])
        self.assertIsNotNone(skill_registry.load_verified(committed["id"]))
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))

    def test_user_rejection_discards_candidate_without_skill_commit(self):
        candidate = self._candidate()
        self.assertTrue(
            skill_registry.discard_pending(
                candidate["id"], "wrong folder", user_rejected=True
            )
        )
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))
        self.assertEqual(skill_registry._load_list(skill_registry.SKILLS_FILE), [])
        invalidated = skill_registry._load_list(skill_registry.INVALIDATED_FILE)
        self.assertEqual(invalidated[0]["status"], "user_rejected")

    def test_ai_selects_only_exact_verified_skill_id(self):
        candidate = self._candidate()
        skill_registry.mark_execution_success(
            candidate["id"],
            {
                "success": True,
                "completed": True,
                "action": "installed_fm_tactic",
                "name": "winner.fmf",
                "destination": "Football Manager 2026 tactics",
            },
        )
        skill = skill_registry.commit_verified(candidate["id"], "成功")
        model = Mock(
            return_value={"decision": "USE", "skill_id": skill["id"]}
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = skill_registry.match_verified(
                "给我装一个适合红魔的 FM26 阵型"
            )
        self.assertEqual(selected["id"], skill["id"])
        self.assertTrue(model.called)

    def test_ai_can_restore_exact_pending_candidate_after_checkpoint_expiry(self):
        candidate = self._candidate()
        resume_request = "网上找一个适合曼联的强力 FM26 战术并导入电脑"
        model = Mock(return_value={
            "decision": "RESUME",
            "candidate_id": candidate["id"],
            "resume_request": resume_request,
            "reason": "Recent context confirms the pending FM task",
        })
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            matched = skill_registry.match_pending_resume(
                "继续",
                "Bekki: 初步已完成，需要继续找战术吗？",
            )
        self.assertEqual(matched["skill"]["id"], candidate["id"])
        self.assertEqual(matched["resume_request"], resume_request)
        self.assertTrue(model.called)

    def test_pending_resume_retries_large_equivalent_candidate_catalog(self):
        older = self._candidate()
        newer = self._candidate(
            "Install a Manchester United tactic using the learned method"
        )
        resume_request = "网上找一个适合曼联的强力 FM26 战术并导入电脑"
        model = Mock(side_effect=[None, {
            "decision": "RESUME",
            "candidate_id": newer["id"],
            "resume_request": resume_request,
            "reason": "Latest coherent equivalent retry",
        }])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            matched = skill_registry.match_pending_resume(
                "继续",
                "Bekki: 如果需要，请回复继续。",
            )
        self.assertNotEqual(older["id"], newer["id"])
        self.assertEqual(matched["skill"]["id"], newer["id"])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].kwargs["num_predict"], 1800)
        self.assertEqual(model.call_args_list[1].kwargs["num_predict"], 3000)
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 8192)

    def test_ai_can_explicitly_continue_learning_checkpoint(self):
        model = Mock(return_value="CONTINUE")
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        pending = {
            "type": "content_learning_continue",
            "original_request": "找战术并安装",
            "approval_payload": {"skill_candidate_id": "candidate-id"},
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            verdict = skill_registry.classify_learning_checkpoint(
                "继续", pending, "Bekki: 如果需要，请回复继续。"
            )
        self.assertEqual(verdict, "CONTINUE")
        self.assertEqual(
            model.call_args.args[0],
            "prompts/casper_skill_learning_checkpoint.txt",
        )
        self.assertEqual(
            model.call_args.kwargs["model_name"], "llama3.2:latest"
        )
        self.assertEqual(model.call_args.kwargs["num_predict"], 512)
        self.assertEqual(model.call_args.kwargs["num_ctx"], 4096)

    def test_empty_user_verification_retries_with_independent_model(self):
        model = Mock(side_effect=["", "ACCEPT"])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        pending = {
            "type": "content_skill_verification",
            "verification_kind": "opened_destination_folder",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            verdict = skill_registry.classify_user_verification(
                "对，这个文件夹是正确的", pending
            )
        self.assertEqual(verdict, "ACCEPT")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_skill_user_verification.txt",
        )
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(model.call_args_list[0].kwargs["num_predict"], 512)
        self.assertEqual(model.call_args_list[0].kwargs["num_ctx"], 4096)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_skill_user_verification_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma3:12b"
        )
        self.assertEqual(model.call_args_list[1].kwargs["num_predict"], 1800)
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 8192)

    def test_invalid_user_verification_outputs_fail_closed(self):
        model = Mock(return_value="CONTINUE")
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            verdict = skill_registry.classify_user_verification(
                "继续", {"type": "content_skill_verification"}
            )
        self.assertEqual(verdict, "CLARIFY")
        self.assertEqual(model.call_count, 2)

    def test_empty_checkpoint_response_retries_with_larger_budget(self):
        model = Mock(side_effect=["", "CONTINUE"])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        pending = {
            "type": "content_learning_continue",
            "original_request": "找战术并安装",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            verdict = skill_registry.classify_learning_checkpoint(
                "继续", pending
            )
        self.assertEqual(verdict, "CONTINUE")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].kwargs["num_predict"], 512
        )
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_skill_learning_checkpoint_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["num_predict"], 2400
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma3:12b"
        )
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 8192)

    def test_invalid_learning_checkpoint_output_fails_closed(self):
        model = Mock(return_value="ACCEPT")
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            verdict = skill_registry.classify_learning_checkpoint(
                "嗯", {"type": "content_learning_continue"}
            )
        self.assertEqual(verdict, "CLARIFY")

    def test_ai_recovers_substantive_request_behind_continue(self):
        model = Mock(
            return_value={
                "found": True,
                "resume_request": "网上找一个适合曼联的强力 FM26 战术并导入电脑",
                "reason": "Earlier explicit request",
            }
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        pending = {
            "type": "content_learning_continue",
            "original_request": "继续",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            request = skill_registry.resolve_resume_request(
                "继续",
                pending,
                "User: 网上找一个适合曼联的强力 FM26 战术并导入电脑",
            )
        self.assertEqual(
            request,
            "网上找一个适合曼联的强力 FM26 战术并导入电脑",
        )
        self.assertEqual(
            model.call_args.kwargs["model_name"], "llama3.2:latest"
        )
        self.assertEqual(model.call_args.kwargs["num_predict"], 1400)
        self.assertEqual(model.call_args.kwargs["num_ctx"], 8192)

    def test_resume_request_retries_with_independent_large_model(self):
        recovered = "网上找一个适合曼联的强力 FM26 战术并导入电脑"
        model = Mock(side_effect=[None, {
            "found": True,
            "resume_request": recovered,
            "reason": "Earlier explicit request",
        }])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            request = skill_registry.resolve_resume_request(
                "继续",
                {"type": "content_learning_continue"},
                "User: " + recovered,
            )
        self.assertEqual(request, recovered)
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_skill_resume_request.txt",
        )
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(model.call_args_list[0].kwargs["num_predict"], 1400)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_skill_resume_request_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma3:12b"
        )
        self.assertEqual(model.call_args_list[1].kwargs["num_predict"], 3600)
        self.assertEqual(model.call_args_list[1].kwargs["num_ctx"], 8192)

    def test_resume_request_recovery_fails_closed_without_evidence(self):
        model = Mock(
            return_value={
                "found": False,
                "resume_request": None,
                "reason": "No substantive request",
            }
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            request = skill_registry.resolve_resume_request(
                "继续", {"type": "content_learning_continue"}, ""
            )
        self.assertEqual(request, "")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma3:12b"
        )


if __name__ == "__main__":
    unittest.main()
