import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from casper import content_learning


class ContentLearningContractTests(unittest.TestCase):
    def test_non_game_capability_fails_closed_before_browser_learning(self):
        plan = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "file_system.open_destination_folder",
            "intent_summary": "Open Recycle Bin",
            "target_app": "Windows",
            "content_kind": "recycle_bin",
            "parameters": [],
            "version_constraints": [],
            "installation_queries": ["Windows Recycle Bin path"],
        }
        self.assertIsNone(
            content_learning._normalize_learning_plan(
                plan,
                "OPEN_DESTINATION_FOLDER",
            )
        )

    def test_learning_plan_uses_distinct_high_budget_retry_contract(self):
        valid = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Open the reusable content destination",
            "target_app": "FM26",
            "content_kind": "tactic",
            "parameters": [],
            "version_constraints": ["FM26"],
            "installation_queries": ["FM26 tactics folder documentation"],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                None,
                valid,
                {"grounded": True, "reason": "current request supports plan"},
                {"compliant": True, "reason": "grounded query"},
            ],
        ) as model:
            result = content_learning._plan(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )
        self.assertEqual(result["target_app"], "FM26")
        self.assertEqual(model.call_count, 4)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_learning_plan.txt",
        )
        self.assertEqual(model.call_args_list[0].args[2], 2200)
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_learning_plan_retry.txt",
        )
        self.assertEqual(model.call_args_list[1].args[2], 3600)
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma4:12b"
        )

    def test_empty_queries_are_repaired_without_regenerating_grounding(self):
        draft = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Open the reusable tactics destination",
            "target_app": "FM26",
            "content_kind": "tactics",
            "parameters": [],
            "version_constraints": ["FM26"],
            "installation_queries": [],
        }
        repaired = {
            "installation_queries": [
                "FM26 tactics folder location file type import guide"
            ]
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                draft,
                {"grounded": True, "reason": "current request supports plan"},
                repaired,
                {"compliant": True, "reason": "specific documentation query"},
            ],
        ) as model:
            result = content_learning._plan(
                "打开 FM26 战术文件夹",
                "旧的曼联战术安装请求",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )

        self.assertEqual(result["target_app"], "FM26")
        self.assertEqual(result["capability"], draft["capability"])
        self.assertEqual(result["skill_scope"], draft["skill_scope"])
        self.assertEqual(result["content_kind"], draft["content_kind"])
        self.assertEqual(
            result["version_constraints"], draft["version_constraints"]
        )
        self.assertEqual(result["intent_summary"], draft["intent_summary"])
        self.assertEqual(result["parameters"], draft["parameters"])
        self.assertEqual(
            result["installation_queries"], repaired["installation_queries"]
        )
        self.assertEqual(
            [call.args[0] for call in model.call_args_list],
            [
                "prompts/casper_content_learning_plan.txt",
                "prompts/casper_content_learning_grounding_review.txt",
                "prompts/casper_content_learning_query.txt",
                "prompts/casper_content_learning_query_review.txt",
            ],
        )

    def test_ai_rejects_placeholder_query_before_browser_discovery(self):
        placeholder = "one complete documentation search"
        draft = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Open a reusable destination",
            "target_app": "FM26",
            "content_kind": "tactics",
            "parameters": [],
            "version_constraints": [],
            "installation_queries": [placeholder],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                draft,
                {"grounded": True, "reason": "current request supports plan"},
                {"installation_queries": [placeholder]},
            ],
        ), patch.object(content_learning, "_discover") as discover:
            result = content_learning.execute(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )

        self.assertTrue(result["needs_clarification"])
        discover.assert_not_called()

    def test_rejected_query_uses_independent_recovery_then_review(self):
        draft = {
            "supported": True,
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Open a reusable destination",
            "target_app": "FM26",
            "content_kind": "tactics",
            "parameters": [],
            "version_constraints": [],
            "installation_queries": ["documentation search"],
        }
        recovered = {
            "installation_queries": [
                "FM26 tactics folder location file type import guide"
            ]
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                draft,
                {"grounded": True, "reason": "current request supports plan"},
                recovered,
                {"compliant": True, "reason": "grounded and executable"},
            ],
        ) as model:
            result = content_learning._plan(
                "打开 FM26 战术文件夹",
                "",
                requested_skill_scope="OPEN_DESTINATION_FOLDER",
            )

        self.assertEqual(
            result["installation_queries"], recovered["installation_queries"]
        )
        self.assertEqual(
            [call.args[0] for call in model.call_args_list],
            [
                "prompts/casper_content_learning_plan.txt",
                "prompts/casper_content_learning_grounding_review.txt",
                "prompts/casper_content_learning_query_retry.txt",
                "prompts/casper_content_learning_query_review.txt",
            ],
        )

    def test_placeholder_query_is_rejected_without_calling_ai(self):
        plan = {
            "installation_queries": ["one complete documentation search"],
        }
        with patch.object(content_learning, "_ai") as model:
            compliant, reason = content_learning._review_documentation_queries(
                "打开 FM26 战术文件夹", plan
            )
        self.assertFalse(compliant)
        self.assertIn("Placeholder", reason)
        model.assert_not_called()

    def test_template_query_is_rejected_without_calling_ai(self):
        plan = {
            "installation_queries": ["<target app> folder documentation"],
        }
        with patch.object(content_learning, "_ai") as model:
            compliant, reason = content_learning._review_documentation_queries(
                "打开 FM26 战术文件夹", plan
            )
        self.assertFalse(compliant)
        self.assertIn("Template", reason)
        model.assert_not_called()

    def test_learning_plan_prompts_do_not_embed_old_schema_sentinels(self):
        project_root = Path(content_learning.__file__).resolve().parent.parent
        sentinels = (
            "one complete documentation search",
            "stable reusable capability",
            "grounded application identity",
            "reusable operation only",
        )
        for name in (
            "casper_content_learning_plan.txt",
            "casper_content_learning_plan_retry.txt",
        ):
            with self.subTest(prompt=name):
                text = (project_root / "prompts" / name).read_text(
                    encoding="utf-8"
                ).casefold()
                for sentinel in sentinels:
                    self.assertNotIn(sentinel, text)

    def test_query_repair_has_distinct_empty_output_recovery(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "FM26",
            "content_kind": "tactics",
            "version_constraints": [],
        }
        recovered = {
            "installation_queries": [
                "FM26 tactics folder location file type import guide"
            ]
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[None, recovered],
        ) as model:
            result = content_learning._repair_documentation_queries(
                "打开 FM26 战术文件夹", plan
            )
        self.assertEqual(result, recovered["installation_queries"])
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_learning_query.txt",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_learning_query_retry.txt",
        )
        self.assertGreater(
            model.call_args_list[1].args[2],
            model.call_args_list[0].args[2],
        )

    def test_grounding_review_has_distinct_invalid_output_recovery(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "intent_summary": "Locate and open the tactics destination",
            "target_app": "FM26",
            "content_kind": "tactics",
            "parameters": [],
            "version_constraints": ["FM26"],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[
                None,
                {"grounded": True, "reason": "supported by current request"},
            ],
        ) as model:
            grounded, _reason = (
                content_learning._review_learning_plan_grounding(
                    "打开 FM26 战术文件夹", "", plan
                )
            )

        self.assertTrue(grounded)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_learning_grounding_review.txt",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_learning_grounding_review_retry.txt",
        )
        self.assertEqual(
            model.call_args_list[0].kwargs["model_name"], "gemma4:12b"
        )
        self.assertEqual(
            model.call_args_list[1].kwargs["model_name"], "gemma4:12b"
        )
        self.assertGreater(
            model.call_args_list[1].args[2],
            model.call_args_list[0].args[2],
        )
        self.assertGreater(
            model.call_args_list[1].kwargs["num_ctx"],
            model.call_args_list[0].kwargs["num_ctx"],
        )

    def test_query_review_has_distinct_invalid_output_recovery(self):
        plan = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "capability": "game_content.open_destination_folder",
            "target_app": "FM26",
            "content_kind": "tactics",
            "installation_queries": [
                "FM26 tactics folder location file type import guide"
            ],
        }
        with patch.object(
            content_learning,
            "_ai",
            side_effect=[None, {"compliant": True, "reason": "valid"}],
        ) as model:
            compliant, _reason = content_learning._review_documentation_queries(
                "打开 FM26 战术文件夹", plan
            )
        self.assertTrue(compliant)
        self.assertEqual(
            model.call_args_list[0].args[0],
            "prompts/casper_content_learning_query_review.txt",
        )
        self.assertEqual(
            model.call_args_list[1].args[0],
            "prompts/casper_content_learning_query_review_retry.txt",
        )
        self.assertGreater(
            model.call_args_list[1].args[2],
            model.call_args_list[0].args[2],
        )

    def test_adapter_contract_rejects_jar_even_if_ai_calls_it_compatible(self):
        destination = {
            "id": "destination-id",
            "name": "Football Manager tactics",
            "path": "C:/Users/Test/Documents/FM/tactics",
            "kind": "fm_tactic_destination",
        }
        procedure = {
            "skill_scope": "INSTALL_CONTENT",
            "expected_file_types": [".jar"],
            "destination_hints": ["mods folder"],
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
        ), patch.object(content_learning.os, "makedirs") as makedirs, patch.object(
            content_learning.os, "startfile", create=True
        ) as startfile:
            selected, error = content_learning._prepare_local_destination(
                {"target_app": "Example Game", "content_kind": "mod"},
                procedure,
            )
        self.assertIsNone(selected)
        self.assertIn("执行契约", error)
        makedirs.assert_not_called()
        startfile.assert_not_called()

    def test_adapter_contract_uses_exact_declared_types_scope_and_kind(self):
        good = {
            "skill_scope": "OPEN_DESTINATION_FOLDER",
            "expected_file_types": [".FMF"],
        }
        destination = {"kind": "fm_tactic_destination"}
        self.assertTrue(
            content_learning._validate_adapter_contract(
                good, "FM_TACTIC", destination
            )
        )
        self.assertFalse(
            content_learning._validate_adapter_contract(
                {**good, "skill_scope": "UNKNOWN"},
                "FM_TACTIC",
                destination,
            )
        )
        self.assertFalse(
            content_learning._validate_adapter_contract(
                good, "FM_TACTIC", {"kind": "other_destination"}
            )
        )


if __name__ == "__main__":
    unittest.main()
