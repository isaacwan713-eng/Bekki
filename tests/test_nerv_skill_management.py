import unittest
from unittest import mock
from pathlib import Path
import tempfile

from nerv import skill_management
from nerv.core import NervCore


SKILL = {
    "id": "skill_76cd8e8fc461834f702c",
    "capability": "game_content.open_destination_folder",
    "skill_scope": "OPEN_DESTINATION_FOLDER",
    "target_app": "Football Manager 2026",
    "content_kind": "tactics",
    "intent_summary": "Locate and open the reusable tactics destination folder",
}


class NervSkillManagementTests(unittest.TestCase):
    def test_resolver_accepts_only_exact_catalog_id(self):
        model = mock.Mock(
            return_value={
                "decision": "FORGET",
                "skill_id": SKILL["id"],
                "reason": "exact match",
            }
        )
        unload = mock.Mock()
        result = skill_management.resolve_forget_request(
            "忘掉打开 FM26 战术文件夹这个技能", [SKILL], model, unload
        )
        self.assertEqual(result["status"], "MATCHED")
        self.assertEqual(result["skill"]["id"], SKILL["id"])
        self.assertEqual(model.call_args.kwargs["model_name"], "gemma3:12b")
        unload.assert_called_once_with("gemma3:12b")

    def test_resolver_rejects_invented_id(self):
        model = mock.Mock(
            return_value={
                "decision": "FORGET",
                "skill_id": "skill_invented",
                "reason": "guess",
            }
        )
        result = skill_management.resolve_forget_request(
            "忘掉技能", [SKILL], model
        )
        self.assertEqual(result["status"], "CLARIFY")
        self.assertIsNone(result["skill"])

    def test_confirmation_is_closed_and_releases_model(self):
        model = mock.Mock(return_value="CONFIRM")
        unload = mock.Mock()
        verdict = skill_management.classify_forget_confirmation(
            "确认忘掉",
            {"approval_payload": {"skill_id": SKILL["id"]}},
            model,
            unload,
        )
        self.assertEqual(verdict, "CONFIRM")
        unload.assert_called_once_with("gemma3:12b")

    def test_invalid_confirmation_fails_closed(self):
        verdict = skill_management.classify_forget_confirmation(
            "也许吧", {}, mock.Mock(return_value="MAYBE")
        )
        self.assertEqual(verdict, "AMBIGUOUS")

    def test_display_name_does_not_expand_verified_scope(self):
        self.assertEqual(
            skill_management.display_name(SKILL, "zh-CN"),
            "打开 Football Manager 2026 的战术文件夹",
        )

    def test_core_forget_delegates_to_casper_then_reconciles(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = NervCore(model_call=mock.Mock(), base_dir=temporary)
            with mock.patch(
                "casper.skill_registry.forget_verified", return_value=dict(SKILL)
            ) as forget, mock.patch.object(
                core.learning, "reconcile_verified_casper_skills"
            ) as reconcile:
                removed = core.forget_verified_skill(SKILL["id"], confirmed=True)
        self.assertEqual(removed["id"], SKILL["id"])
        forget.assert_called_once_with(SKILL["id"], confirmed=True)
        reconcile.assert_called_once_with()

    def test_runtime_wires_two_turn_confirmation_before_delete(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('"nerv_skill_forget_confirmation"', source)
        self.assertIn("resolve_skill_forget(message)", source)
        self.assertIn("classify_skill_forget_confirmation(message, pending)", source)
        self.assertIn("forget_verified_skill(skill_id, confirmed=True)", source)
        self.assertLess(
            source.index("classify_skill_forget_confirmation(message, pending)"),
            source.index("forget_verified_skill(skill_id, confirmed=True)"),
        )


if __name__ == "__main__":
    unittest.main()
