import unittest
import sys
import types
from unittest.mock import Mock, patch

from casper import content_learning, skill_registry


class ContentLearningTests(unittest.TestCase):
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

    def test_local_destination_is_opened_only_after_ai_selection(self):
        destination = {
            "id": "destination-id",
            "name": "Football Manager 2026 tactics",
            "path": "C:/Users/Test/Documents/FM26/tactics",
        }
        procedure = {"destination_hints": ["tactics folder"]}
        with patch.object(
            content_learning, "_select_local_adapter", return_value="FM_TACTIC"
        ), patch.object(
            content_learning.game_content,
            "discover_fm_tactic_destinations",
            return_value=[destination],
        ), patch.object(
            content_learning, "_select_destination", return_value=destination
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
