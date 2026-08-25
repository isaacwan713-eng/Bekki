import unittest
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

from casper import content_learning, skill_registry


class ContentLearningTests(unittest.TestCase):
    def test_learning_plan_uses_strict_model_contract_and_preserves_ai_identity(self):
        model_result = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Locate and open the tactics destination",
            "target_app": "FM26",
            "content_kind": "tactic",
            "version_constraints": ["FM26"],
            "parameters": [],
            "installation_queries": ["FM26 tactics folder documentation"],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                model_result,
                {"grounded": True, "reason": "current request supports plan"},
                {"compliant": True, "reason": "grounded query"},
            ],
        ) as model:
            plan = content_learning._plan(
                "打开 FM26 战术文件夹",
                "早先讨论过推荐战术",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        self.assertEqual(plan["target_app"], "FM26")
        self.assertEqual(plan["skill_scope"], "OPEN_DESTINATION_FOLDER")
        self.assertEqual(model.call_args_list[0].args[2], 2200)
        self.assertEqual(model.call_args_list[0].kwargs["num_ctx"], 8192)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"], "gemma3:12b"
        )

        prompt_path = (
            Path(content_learning.__file__).resolve().parent.parent
            / "prompts"
            / "casper_content_learning_plan.txt"
        )
        prompt = prompt_path.read_text(encoding="utf-8")
        self.assertIn(
            "Preserve application identity from CURRENT_REQUEST", prompt
        )
        self.assertNotIn("FM26 always means", prompt)
        self.assertNotIn("never FIFA Manager", prompt)

    def test_copied_cross_app_plan_fails_grounding_before_discovery(self):
        copied_example = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Locate and open the shader-pack destination",
            "target_app": "Minecraft Java Edition",
            "content_kind": "shader packs",
            "version_constraints": [],
            "parameters": [],
            "installation_queries": [
                "Minecraft Java Edition shaderpacks folder location guide"
            ],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                copied_example,
                {"grounded": False, "reason": "wrong application identity"},
                copied_example,
                {"grounded": False, "reason": "copied example identity"},
            ],
        ) as model, patch.object(content_learning, "_discover") as discover:
            result = content_learning.execute(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )

        self.assertTrue(result["needs_clarification"])
        discover.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in model.call_args_list],
            [
                "prompts/casper_content_learning_plan.txt",
                "prompts/casper_content_learning_grounding_review.txt",
                "prompts/casper_content_learning_plan_retry.txt",
                "prompts/casper_content_learning_grounding_review.txt",
            ],
        )

    def test_invalid_query_reviews_and_failed_repair_stop_before_discovery(self):
        plan = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Locate and open the tactics destination",
            "target_app": "FM26",
            "content_kind": "tactics",
            "version_constraints": ["FM26"],
            "parameters": [],
            "installation_queries": [
                "FM26 tactics folder location file type import guide"
            ],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                plan,
                {"grounded": True, "reason": "supported by current request"},
                None,
                {"compliant": "true", "reason": "wrong boolean type"},
                None,
            ],
        ) as model, patch.object(content_learning, "_discover") as discover:
            result = content_learning.execute(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )

        self.assertTrue(result["needs_clarification"])
        discover.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in model.call_args_list],
            [
                "prompts/casper_content_learning_plan.txt",
                "prompts/casper_content_learning_grounding_review.txt",
                "prompts/casper_content_learning_query_review.txt",
                "prompts/casper_content_learning_query_review_retry.txt",
                "prompts/casper_content_learning_query_retry.txt",
            ],
        )

    def test_folder_open_is_machine_verified_before_user_confirmation(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "installation_queries": ["FM26 tactics folder documentation"],
        }
        procedure = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
        }
        destination = {
            "id": "destination-id",
            "name": "Football Manager 2026 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
            "kind": "fm_tactic_destination",
        }
        candidate = {
            "id": "candidate-id",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "destination_name": destination["name"],
        }
        marked = {**candidate, "status": "pending_user_verification"}
        with patch.object(content_learning, "_plan", return_value=plan), patch.object(
            content_learning, "_discover", return_value=([{"id": "source"}], None)
        ), patch.object(
            content_learning, "_rank", return_value=[{"id": "source"}]
        ), patch.object(
            content_learning, "_read", return_value=[{"source_id": "source"}]
        ), patch.object(
            content_learning, "_extract_procedure", return_value=procedure
        ), patch.object(
            content_learning,
            "_prepare_local_destination",
            return_value=(destination, ""),
        ), patch.object(
            skill_registry, "create_pending", return_value=candidate
        ), patch.object(
            skill_registry, "mark_execution_success", return_value=marked
        ) as mark:
            result = content_learning.execute(
                "打开战术文件夹并推荐三个战术",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        self.assertEqual(result["action"], "folder_skill_awaiting_user_verification")
        self.assertTrue(result["requires_user_verification"])
        mark.assert_called_once()
        self.assertEqual(
            mark.call_args.args[1]["action"], "opened_fm_tactic_folder"
        )

    def test_learning_phase_creates_only_temporary_skill_candidate(self):
        plan = {
            "capability": "game_content.install",
            "intent_summary": "Install FM tactics",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "parameters": ["team_or_play_style"],
            "version_constraints": ["FM26"],
            "installation_queries": ["FM26 install tactics"],
        }
        procedure = {
            "capability": "game_content.install",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "expected_file_types": [".fmf"],
            "destination_hints": ["tactics folder"],
            "installation_steps": ["Move file"],
        }
        destination = {
            "id": "destination-id",
            "name": "Football Manager 2026 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
            "kind": "fm_tactic_destination",
        }
        pending = {
            "id": "candidate-id",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "destination_name": "Football Manager 2026 tactics",
        }
        with patch.object(content_learning, "_plan", return_value=plan), patch.object(
            content_learning, "_discover", return_value=([{"id": "source"}], None)
        ), patch.object(
            content_learning, "_rank", return_value=[{"id": "source"}]
        ), patch.object(
            content_learning, "_read", return_value=[{"source_id": "source"}]
        ), patch.object(
            content_learning, "_extract_procedure", return_value=procedure
        ), patch.object(
            content_learning,
            "_prepare_local_destination",
            return_value=(destination, ""),
        ), patch.object(
            skill_registry, "create_pending", return_value=pending
        ) as create_pending:
            result = content_learning.execute("找战术并安装", "")
        self.assertEqual(result["action"], "learned_content_skill_candidate")
        self.assertTrue(result["requires_continuation"])
        self.assertEqual(result["skill_candidate_id"], "candidate-id")
        create_pending.assert_called_once_with(
            procedure, destination, "找战术并安装"
        )

    def test_empty_ranked_sources_stop_before_procedure_ai(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "FM26",
            "content_kind": "tactics",
            "installation_queries": ["FM26 tactics folder documentation"],
        }
        with patch.object(
            content_learning, "_plan", return_value=plan
        ), patch.object(
            content_learning,
            "_discover",
            return_value=([{"id": "source-id"}], None),
        ), patch.object(
            content_learning, "_rank", return_value=[]
        ), patch.object(
            content_learning, "_extract_procedure"
        ) as extract:
            result = content_learning.execute(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        self.assertTrue(result["needs_clarification"])
        extract.assert_not_called()

    def test_empty_rendered_pages_stop_before_procedure_ai(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "FM26",
            "content_kind": "tactics",
            "installation_queries": ["FM26 tactics folder documentation"],
        }
        ranked = [{"id": "source-id"}]
        with patch.object(
            content_learning, "_plan", return_value=plan
        ), patch.object(
            content_learning,
            "_discover",
            return_value=(ranked, None),
        ), patch.object(
            content_learning, "_rank", return_value=ranked
        ), patch.object(
            content_learning, "_read", return_value=[]
        ), patch.object(
            content_learning, "_extract_procedure"
        ) as extract:
            result = content_learning.execute(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        self.assertTrue(result["needs_clarification"])
        extract.assert_not_called()

    def test_local_destination_is_opened_only_after_ai_selection(self):
        destination = {
            "id": "destination-id",
            "name": "Football Manager 2026 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
            "kind": "fm_tactic_destination",
        }
        procedure = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "expected_file_types": [".fmf"],
            "destination_hints": ["tactics folder"],
        }
        with patch.object(
            content_learning, "_select_local_adapter", return_value="FM_TACTIC"
        ), patch.object(
            content_learning.game_content,
            "discover_fm_tactic_destinations",
            return_value=[destination],
        ), patch.object(
            content_learning, "_select_destination", return_value=destination
        ), patch.object(
            content_learning, "_review_local_binding", return_value=True
        ), patch.object(
            content_learning.sys, "platform", "win32"
        ), patch.object(
            content_learning.os, "makedirs"
        ) as makedirs, patch.object(
            content_learning.os, "startfile", create=True
        ) as startfile:
            selected, error = content_learning._prepare_local_destination(
                {"target_app": "FM26"}, procedure
            )
        self.assertEqual(error, "")
        self.assertEqual(selected, destination)
        makedirs.assert_called_once_with(destination["path"], exist_ok=True)
        startfile.assert_called_once_with(destination["path"])
        self.assertEqual(procedure["local_adapter"], "FM_TACTIC")

    def test_bare_continue_cannot_invent_a_learning_target(self):
        model = Mock(
            return_value={
                "supported": False,
                "reason": "missing grounded target",
            }
        )
        with patch.object(content_learning, "_ai", model):
            plan = content_learning._plan("继续", "Bekki: 请回复继续")
        self.assertIsNone(plan)
        self.assertEqual(model.call_count, 2)

    def test_incoherent_local_binding_stops_before_folder_write(self):
        destination = {
            "id": "destination-id",
            "name": "Football Manager 26 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
            "kind": "fm_tactic_destination",
        }
        procedure = {
            "target_app": "Minecraft",
            "content_kind": "mod",
            "expected_file_types": [".jar"],
            "destination_hints": ["Minecraft mods folder"],
        }
        with patch.object(
            content_learning, "_select_local_adapter", return_value="FM_TACTIC"
        ), patch.object(
            content_learning.game_content,
            "discover_fm_tactic_destinations",
            return_value=[destination],
        ), patch.object(
            content_learning, "_select_destination", return_value=destination
        ), patch.object(
            content_learning, "_review_local_binding", return_value=False
        ), patch.object(
            content_learning.os, "makedirs"
        ) as makedirs, patch.object(
            content_learning.os, "startfile", create=True
        ) as startfile:
            selected, error = content_learning._prepare_local_destination(
                {"target_app": "Minecraft", "content_kind": "mod"},
                procedure,
            )
        self.assertIsNone(selected)
        self.assertIn("彼此不一致", error)
        makedirs.assert_not_called()
        startfile.assert_not_called()

    def test_binding_review_uses_ai_declaration_not_python_semantics(self):
        model = Mock(
            return_value={
                "compatible": False,
                "reason": "Minecraft jar conflicts with FM tactic folder",
            }
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            compatible = content_learning._review_local_binding(
                {"target_app": "Minecraft", "content_kind": "mod"},
                {
                    "target_app": "Minecraft",
                    "content_kind": "mod",
                    "expected_file_types": [".jar"],
                },
                "FM_TACTIC",
                {"id": "destination-id", "name": "FM26 tactics"},
            )
        self.assertFalse(compatible)
        self.assertEqual(model.call_count, 1)

    def test_destination_selection_retries_empty_output_compactly(self):
        destinations = [
            {
                "id": "destination-id",
                "name": "Football Manager 26 tactics",
                "path": "C:/Users/Test/Documents/FM26/tactics",
            }
        ]
        model = Mock(
            side_effect=[None, {"destination_id": "destination-id"}]
        )
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = content_learning._select_destination(
                {"target_app": "Football Manager 26"},
                {"destination_hints": ["tactics folder"]},
                destinations,
            )
        self.assertEqual(selected["id"], "destination-id")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"],
            "llama3.2:latest",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_destination_select_retry.txt",
        )

    def test_local_adapter_selection_retries_invalid_output(self):
        model = Mock(side_effect=[None, {"adapter": "FM_TACTIC"}])
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)
        with patch.dict(sys.modules, {"tools": fake_tools}):
            adapter = content_learning._select_local_adapter(
                {"target_app": "Football Manager 26"},
                {"expected_file_types": [".fmf"]},
            )
        self.assertEqual(adapter, "FM_TACTIC")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_local_adapter_retry.txt",
        )


if __name__ == "__main__":
    unittest.main()
