import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nerv import governance
from nerv.learning_engine import LearningEngine


def verified_skill(**overrides):
    value = {
        "id": "skill_1234567890abcdef1234",
        "status": "verified",
        "user_verified": True,
        "capability": "game_content.install",
        "skill_scope": "INSTALL_CONTENT",
        "intent_summary": "Install Football Manager tactics",
        "target_app": "Football Manager 2026",
        "content_kind": "tactic",
        "local_adapter": "FM_TACTIC",
        "parameters": ["team", "play_style"],
        "applicability": {
            "platform": "win32",
            "version_constraints": ["FM26"],
        },
        "verified_destination_path": "C:/Private/Isaac/Documents/FM26/tactics",
        "source_urls": ["https://example.test/private-source"],
        "machine_verification": {
            "success": True,
            "completed": True,
            "action": "installed_fm_tactic",
        },
    }
    value.update(overrides)
    return value


class NervLearningTests(unittest.TestCase):
    def test_observation_never_promotes_a_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.record_result(
                "打开回收站",
                "DEVICE_ACTION",
                "completed",
                action="opened_recycle_bin",
            )
            with mock.patch.object(
                engine, "_casper_verified_snapshot", return_value=(True, [])
            ):
                self.assertEqual(engine.verified_items(), [])

    def test_empty_final_context_is_explicit_empty_array(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            with mock.patch.object(
                engine, "_casper_verified_snapshot", return_value=(True, [])
            ):
                self.assertEqual(
                    engine.context_for("melchior", "你目前学会了哪些操作？"),
                    "[]",
                )

    def test_verified_import_requires_machine_and_user_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            rejected = engine.accept_verified_casper_skill(
                verified_skill(user_verified=False),
                "成功了",
            )
            self.assertIsNone(rejected)
            self.assertEqual(engine._load_skills()["items"], [])

    def test_verified_skill_is_saved_as_sanitized_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            learned = engine.accept_verified_casper_skill(
                verified_skill(),
                "已经成功安装并能正常使用",
                session_id="private-session-id",
            )
            self.assertEqual(learned["state"], "VERIFIED")
            rendered = json.dumps(engine._load_skills(), ensure_ascii=False)
            self.assertNotIn("C:/Private", rendered)
            self.assertNotIn("private-source", rendered)
            self.assertNotIn("已经成功安装", rendered)
            self.assertNotIn("private-session-id", rendered)

    def test_duplicate_confirmation_updates_one_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.accept_verified_casper_skill(verified_skill(), "成功了")
            learned = engine.accept_verified_casper_skill(
                verified_skill(), "再次确认成功"
            )
            self.assertEqual(learned["confirmation_count"], 2)
            self.assertEqual(len(engine._load_skills()["items"]), 1)

    def test_learning_context_is_only_exposed_to_final_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.accept_verified_casper_skill(verified_skill(), "成功了")
            with mock.patch.object(
                engine,
                "_casper_verified_snapshot",
                return_value=(True, [verified_skill()]),
            ):
                context = engine.context_for("melchior", "你学会了什么？")
                self.assertIn("Football Manager 2026", context)
                self.assertEqual(engine.context_for("magi"), "")
                self.assertEqual(engine.context_for("external_ai"), "")

    def test_open_folder_scope_repairs_legacy_install_wording_in_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            skill = verified_skill(
                capability="game_content.open_destination_folder",
                skill_scope="OPEN_DESTINATION_FOLDER",
                intent_summary="Copy a .fmf tactic into the tactics folder",
                content_kind="tactics",
                parameters=["tactic_file"],
                machine_verification={
                    "success": True,
                    "completed": True,
                    "action": "opened_fm_tactic_folder",
                },
            )
            engine.accept_verified_casper_skill(skill, "打开对了")
            with mock.patch.object(
                engine,
                "_casper_verified_snapshot",
                return_value=(True, [skill]),
            ):
                context = engine.context_for("melchior", "你学会了什么？")
            self.assertIn(
                "Locate and open the reusable tactics destination folder",
                context,
            )
            self.assertNotIn("Copy a .fmf", context)
            self.assertIn('"parameters":[]', context)

    def test_local_legacy_open_folder_summary_is_repaired_without_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            governance.save_json(
                engine.skills_path,
                {
                    "schema_version": 1,
                    "revision": 1,
                    "items": [
                        {
                            "id": "skill_76cd8e8fc461834f702c",
                            "state": "VERIFIED",
                            "capability": "game_content.open_destination_folder",
                            "skill_scope": "OPEN_DESTINATION_FOLDER",
                            "target_app": "Football Manager 2026",
                            "content_kind": "tactics",
                            "local_adapter": "FM_TACTIC",
                            "intent_summary": (
                                "Copy a .fmf tactics file to the Football "
                                "Manager 2026 tactics folder"
                            ),
                            "parameters": ["tactic_file"],
                            "source": "casper_verified_skill",
                        }
                    ],
                },
            )
            with mock.patch.object(
                engine,
                "_casper_verified_snapshot",
                return_value=(False, []),
            ):
                context = engine.context_for("melchior", "你学会了什么？")
            self.assertIn(
                "Locate and open the reusable tactics destination folder",
                context,
            )
            self.assertNotIn("Copy a .fmf", context)
            stored = governance.load_json(engine.skills_path, {})
            self.assertEqual(stored["revision"], 2)
            self.assertEqual(stored["items"][0]["parameters"], [])

    def test_inventory_reply_cannot_expand_open_folder_into_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            skill = verified_skill(
                capability="game_content.open_destination_folder",
                skill_scope="OPEN_DESTINATION_FOLDER",
                intent_summary="Copy a .fmf tactic into the tactics folder",
                content_kind="tactics",
                parameters=["tactic_file"],
                machine_verification={
                    "success": True,
                    "completed": True,
                    "action": "opened_fm_tactic_folder",
                },
            )
            engine.accept_verified_casper_skill(skill, "对了")
            with mock.patch.object(
                engine,
                "_casper_verified_snapshot",
                return_value=(False, []),
            ):
                reply, count = engine.inventory_reply("zh-CN")
            self.assertEqual(count, 1)
            self.assertIn("打开 Football Manager 2026 的战术文件夹", reply)
            self.assertNotIn("复制", reply)
            self.assertNotIn(".fmf", reply)

    def test_user_rejection_records_event_but_not_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.record_candidate_rejected(
                "candidate_private_value", session_id="session-private"
            )
            self.assertEqual(engine._load_skills()["items"], [])
            event_text = (Path(temporary) / "data/nerv/learning_events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"state": "DEPRECATED"', event_text)
            self.assertNotIn("candidate_private_value", event_text)

    def test_missing_authoritative_skill_deprecates_nerv_mirror(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.accept_verified_casper_skill(verified_skill(), "成功了")
            with mock.patch.object(
                engine, "_casper_verified_snapshot", return_value=(True, [])
            ):
                self.assertEqual(engine.verified_items(), [])
            self.assertEqual(
                engine._load_skills()["items"][0]["state"], "DEPRECATED"
            )

    def test_forgotten_authoritative_skill_deprecates_active_mirror(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.accept_verified_casper_skill(verified_skill(), "成功了")
            with mock.patch.object(
                engine, "_casper_verified_snapshot", return_value=(True, [])
            ):
                engine.reconcile_verified_casper_skills()
            stored = engine._load_skills()["items"][0]
            self.assertEqual(stored["state"], "DEPRECATED")
            self.assertIn("deprecated_at", stored)

    def test_adapter_failure_does_not_deprecate_last_verified_view(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            engine.accept_verified_casper_skill(verified_skill(), "成功了")
            with mock.patch.object(
                engine, "_casper_verified_snapshot", return_value=(False, [])
            ):
                self.assertEqual(len(engine.verified_items()), 1)


class NervLearningIntegrationTests(unittest.TestCase):
    def test_runtime_has_verified_learning_bridge_and_context(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("nerv_core.accept_verified_skill", source)
        self.assertIn("nerv_core.reject_skill_candidate", source)
        self.assertIn("NERV Verified Learning Context", source)
        self.assertIn("[NERV LEARNING VERIFIED]", source)
        self.assertIn("[NERV LEARNING CONTEXT]", source)
        self.assertIn("Never substitute built-in", source)
        self.assertIn("CURRENT AUTHORITATIVE VIEW", source)
        self.assertIn("overrides every older assistant statement", source)
        self.assertIn('[NERV LEARNING DIRECT]', source)
        self.assertIn('inventory_reply(', source)
        self.assertLess(
            source.index('(\"Recent Conversation\", conversation_text)'),
            source.index(
                '\"NERV Verified Learning Context — CURRENT AUTHORITATIVE VIEW'
            ),
        )


if __name__ == "__main__":
    unittest.main()
