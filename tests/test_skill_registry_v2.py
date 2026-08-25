import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from casper import skill_registry


class SkillRegistryV2Tests(unittest.TestCase):
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

    def _procedure(
        self,
        scope="INSTALL_CONTENT",
        adapter="FM_TACTIC",
        expected_types=None,
    ):
        return {
            "capability": "game_content.install",
            "skill_scope": scope,
            "intent_summary": "Install a Football Manager tactic",
            "target_app": "Football Manager 2026",
            "content_kind": "tactic",
            "version_constraints": ["FM26"],
            "parameters": ["team_or_play_style"],
            "expected_file_types": expected_types or [".fmf"],
            "destination_hints": ["FM tactics folder"],
            "installation_steps": ["Place the tactic file"],
            "post_install_steps": ["Load it in FM"],
            "source_ids": ["source-id"],
            "source_urls": ["https://example.test/guide"],
            "local_adapter": adapter,
        }

    def _destination(self, kind="fm_tactic_destination"):
        return {
            "id": "destination-id",
            "name": "Football Manager 2026 tactics",
            "path": os.path.join(self.temporary.name, "FM26", "tactics"),
            "kind": kind,
        }

    def _candidate(self, **kwargs):
        procedure = kwargs.pop("procedure", self._procedure())
        destination = kwargs.pop("destination", self._destination())
        request = kwargs.pop(
            "original_request",
            "Find a Manchester United tactic and install it",
        )
        return skill_registry.create_pending(
            procedure,
            destination,
            request,
            **kwargs,
        )

    def _machine_result(self, action="installed_fm_tactic"):
        return {
            "success": True,
            "completed": True,
            "action": action,
            "name": "winner.fmf",
            "destination": "Football Manager 2026 tactics",
        }

    def _mark(self, candidate):
        return skill_registry.mark_execution_success(
            candidate["id"], self._machine_result()
        )

    def _commit(self, candidate, feedback="I can see it in the game"):
        self.assertIsNotNone(self._mark(candidate))
        return skill_registry.commit_verified(candidate["id"], feedback)

    def test_schema_v2_requires_scope_adapter_destination_and_types(self):
        self.assertEqual(skill_registry.SCHEMA_VERSION, 2)
        self.assertEqual(
            skill_registry.ALLOWED_SKILL_SCOPES,
            {"OPEN_DESTINATION_FOLDER", "INSTALL_CONTENT"},
        )

        procedure_fields = ("skill_scope", "local_adapter", "expected_file_types")
        for field in procedure_fields:
            with self.subTest(field=field):
                procedure = self._procedure()
                del procedure[field]
                self.assertIsNone(self._candidate(procedure=procedure))

        for field in ("id", "name", "path", "kind"):
            with self.subTest(field=field):
                destination = self._destination()
                del destination[field]
                self.assertIsNone(self._candidate(destination=destination))

        self.assertIsNone(
            self._candidate(
                procedure=self._procedure(scope="RECOMMEND_CONTENT")
            )
        )
        self.assertIsNone(
            self._candidate(
                procedure=self._procedure(expected_types=["fmf"])
            )
        )
        non_string_destination = self._destination()
        non_string_destination["id"] = 123
        self.assertIsNone(
            self._candidate(destination=non_string_destination)
        )

    def test_pending_creation_deduplicates_exact_operation_deterministically(self):
        first = self._candidate()
        duplicate = self._candidate()

        self.assertIsNotNone(first)
        self.assertEqual(duplicate["id"], first["id"])
        self.assertEqual(duplicate["candidate_key"], first["candidate_key"])
        self.assertEqual(
            len(skill_registry._load_list(skill_registry.PENDING_FILE)), 1
        )

        changed = self._procedure()
        changed["installation_steps"] = ["Use a different exact method"]
        distinct = self._candidate(procedure=changed)
        self.assertNotEqual(distinct["candidate_key"], first["candidate_key"])
        self.assertNotEqual(distinct["id"], first["id"])

    def test_long_request_uses_the_same_bounded_text_for_key_and_record(self):
        request = "  " + ("install this exact tactic " * 80) + "  "
        candidate = self._candidate(original_request=request)

        self.assertIsNotNone(candidate)
        self.assertLessEqual(len(candidate["original_request"]), 900)
        self.assertEqual(
            candidate["candidate_key"],
            skill_registry._candidate_key_from_record(candidate),
        )
        self.assertIsNotNone(skill_registry.load_pending(candidate["id"]))

    def test_identity_and_candidate_key_include_scope_adapter_and_destination_kind(self):
        install = self._candidate()
        folder = self._candidate(
            procedure=self._procedure(scope="OPEN_DESTINATION_FOLDER")
        )
        other_adapter = self._candidate(
            procedure=self._procedure(adapter="FM_TACTIC_V2")
        )
        other_kind = self._candidate(
            destination=self._destination(kind="fm_tactic_destination_v2")
        )

        candidates = (install, folder, other_adapter, other_kind)
        self.assertTrue(all(candidates))
        self.assertEqual(len({item["candidate_key"] for item in candidates}), 4)
        self.assertEqual(
            len(
                {
                    skill_registry._skill_id_from_record(item)
                    for item in candidates
                }
            ),
            4,
        )

    def test_legacy_and_invalid_pending_records_are_quarantined_and_not_matched(self):
        records = [
            {
                "id": "candidate_legacy",
                "schema_version": 1,
                "status": "pending_execution",
            },
            {
                "id": "candidate_invalidv2",
                "schema_version": 2,
                "status": "pending_execution",
            },
        ]
        skill_registry._save_list(
            skill_registry.PENDING_FILE, records, skill_registry.MAX_PENDING
        )
        model = Mock()
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)

        with patch.dict(sys.modules, {"tools": fake_tools}):
            self.assertIsNone(
                skill_registry.match_pending_resume("continue", "old context")
            )

        self.assertFalse(model.called)
        self.assertEqual(
            skill_registry._load_list(skill_registry.PENDING_FILE), []
        )
        invalidated = skill_registry._load_list(
            skill_registry.INVALIDATED_FILE
        )
        self.assertEqual(len(invalidated), 2)
        self.assertTrue(
            all(item["status"] == "invalid_schema" for item in invalidated)
        )
        self.assertTrue(
            all(item["quarantine_source"] == "pending" for item in invalidated)
        )

    def test_expired_candidate_is_filtered_and_quarantined(self):
        expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        candidate = self._candidate(expires_at=expires_at)

        self.assertIsNotNone(candidate)
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))
        invalidated = skill_registry._load_list(
            skill_registry.INVALIDATED_FILE
        )
        self.assertEqual(invalidated[0]["status"], "expired")

    def test_candidate_defaults_to_24_hour_ttl_and_preserves_valid_override(self):
        before = datetime.now(timezone.utc)
        candidate = self._candidate()
        after = datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(candidate["expires_at"])

        self.assertGreaterEqual(
            expiry, before + timedelta(hours=skill_registry.PENDING_TTL_HOURS)
        )
        self.assertLessEqual(
            expiry, after + timedelta(hours=skill_registry.PENDING_TTL_HOURS)
        )

        explicit = (after + timedelta(hours=3)).isoformat()
        overridden = self._candidate(
            original_request="A distinct request",
            expires_at=explicit,
        )
        self.assertEqual(overridden["expires_at"], explicit)
        self.assertIsNone(
            self._candidate(original_request="bad expiry", expires_at="")
        )

    def test_malformed_expected_type_list_is_quarantined(self):
        candidate = self._candidate()
        malformed = dict(candidate)
        malformed["expected_file_types"] = [".fmf", 123]
        skill_registry._save_list(
            skill_registry.PENDING_FILE,
            [malformed],
            skill_registry.MAX_PENDING,
        )

        self.assertIsNone(skill_registry.load_pending(candidate["id"]))
        invalidated = skill_registry._load_list(
            skill_registry.INVALIDATED_FILE
        )
        self.assertEqual(invalidated[0]["status"], "invalid_schema")
        self.assertIn(
            "expected file types", invalidated[0]["invalidated_reason"]
        )

    def test_session_and_operation_filters_are_optional_and_fail_closed(self):
        first = self._candidate(session_id="session-a", operation_id="operation-1")
        duplicate = self._candidate(
            session_id="session-a", operation_id="operation-1"
        )
        other_session = self._candidate(
            session_id="session-b", operation_id="operation-1"
        )

        self.assertEqual(first["id"], duplicate["id"])
        self.assertNotEqual(first["id"], other_session["id"])
        self.assertIsNotNone(skill_registry.load_pending(first["id"]))
        self.assertIsNotNone(
            skill_registry.load_pending(
                first["id"], session_id="session-a", operation_id="operation-1"
            )
        )
        self.assertIsNone(
            skill_registry.load_pending(first["id"], session_id="session-b")
        )
        self.assertEqual(
            [
                item["id"]
                for item in skill_registry._pending_resume_summaries(
                    session_id="session-a"
                )
            ],
            [first["id"]],
        )

    def test_machine_verification_rejects_negative_or_protected_results(self):
        candidate = self._candidate()
        negative_results = {
            "protected_event": {"type": "captcha"},
            "requires_approval": True,
            "needs_clarification": True,
            "cancelled": True,
            "interrupted": True,
            "failed": True,
            "captcha": True,
            "permission_denied": True,
            "user_rejected": True,
        }
        for field, value in negative_results.items():
            with self.subTest(field=field):
                result = self._machine_result()
                result[field] = value
                self.assertIsNone(
                    skill_registry.mark_execution_success(
                        candidate["id"], result
                    )
                )

        self.assertEqual(
            skill_registry.load_pending(candidate["id"])["status"],
            "pending_execution",
        )
        self.assertEqual(
            skill_registry._load_list(skill_registry.SKILLS_FILE), []
        )

    def test_machine_verification_requires_scoped_action_and_exact_destination(self):
        candidate = self._candidate()
        wrong_action = self._machine_result(action="opened_fm_tactic_folder")
        wrong_destination = self._machine_result()
        wrong_destination["destination"] = "Some other folder"
        wrong_destination_id = self._machine_result()
        wrong_destination_id["destination_id"] = "different-id"

        for result in (wrong_action, wrong_destination, wrong_destination_id):
            with self.subTest(result=result):
                self.assertIsNone(
                    skill_registry.mark_execution_success(
                        candidate["id"], result
                    )
                )

        marked = self._mark(candidate)
        self.assertEqual(marked["status"], "pending_user_verification")
        self.assertEqual(
            marked["machine_verification"]["destination_id"],
            candidate["destination_id"],
        )

    def test_open_folder_scope_is_distinct_from_install_scope(self):
        candidate = self._candidate(
            procedure=self._procedure(scope="OPEN_DESTINATION_FOLDER")
        )
        self.assertIsNone(self._mark(candidate))
        marked = skill_registry.mark_execution_success(
            candidate["id"],
            self._machine_result(action="opened_fm_tactic_folder"),
        )
        self.assertEqual(marked["status"], "pending_user_verification")

    def test_commit_requires_nonempty_feedback_and_both_verifications(self):
        candidate = self._candidate()
        self.assertIsNone(
            skill_registry.commit_verified(candidate["id"], "accepted")
        )
        self.assertIsNotNone(self._mark(candidate))
        self.assertIsNone(skill_registry.commit_verified(candidate["id"], ""))
        self.assertIsNone(
            skill_registry.commit_verified(candidate["id"], "   ")
        )
        self.assertIsNone(skill_registry.commit_verified(candidate["id"], True))

        committed = skill_registry.commit_verified(
            candidate["id"], "I can see the tactic"
        )
        self.assertEqual(committed["status"], "verified")
        self.assertTrue(committed["user_verified"])
        self.assertEqual(
            committed["user_acceptance"]["feedback"],
            "I can see the tactic",
        )
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))

    def test_commit_reconciles_after_skill_write_before_pending_removal(self):
        candidate = self._candidate(session_id="session-a")
        self.assertIsNotNone(self._mark(candidate))
        original_save = skill_registry._save_list
        state = {"raised": False}

        def fail_pending_removal(path, items, maximum):
            if path == skill_registry.PENDING_FILE and not state["raised"]:
                state["raised"] = True
                raise skill_registry.RegistryPersistenceError(
                    "simulated crash after Skills write"
                )
            return original_save(path, items, maximum)

        with patch.object(
            skill_registry, "_save_list", side_effect=fail_pending_removal
        ):
            with self.assertRaises(skill_registry.RegistryPersistenceError):
                skill_registry.commit_verified(
                    candidate["id"], "accepted", session_id="session-a"
                )

        written = skill_registry._load_list(skill_registry.SKILLS_FILE)
        self.assertEqual(len(written), 1)
        self.assertIsNotNone(skill_registry.load_pending(candidate["id"]))
        self.assertIsNone(
            skill_registry.commit_verified(
                candidate["id"], "wrong session", session_id="session-b"
            )
        )

        reconciled = skill_registry.commit_verified(
            candidate["id"], "accepted again", session_id="session-a"
        )
        self.assertEqual(reconciled["candidate_id"], candidate["id"])
        self.assertEqual(reconciled["success_count"], 1)
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))
        self.assertEqual(
            len(skill_registry._load_list(skill_registry.SKILLS_FILE)), 1
        )
        self.assertEqual(
            skill_registry.commit_verified(
                candidate["id"], "accepted once more", session_id="session-a"
            )["id"],
            reconciled["id"],
        )

    def test_json_persistence_recovers_backup_and_fails_closed_if_both_corrupt(self):
        path = os.path.join(self.temporary.name, "durable.json")
        skill_registry._save_list(path, [{"value": 1}], 10)
        self.assertTrue(os.path.isfile(path + ".bak"))

        with open(path, "w", encoding="utf-8") as file:
            file.write("{broken")
        self.assertEqual(skill_registry._load_list(path), [{"value": 1}])

        with open(path, "w", encoding="utf-8") as file:
            file.write("{broken primary")
        with open(path + ".bak", "w", encoding="utf-8") as file:
            file.write("{broken backup")
        with self.assertRaises(skill_registry.RegistryCorruptionError):
            skill_registry._load_list(path)

    def test_semantic_matching_remains_ai_owned_with_exact_id_enforcement(self):
        candidate = self._candidate()
        skill = self._commit(candidate)
        model = Mock(return_value={"decision": "USE", "skill_id": skill["id"]})
        fake_tools = types.SimpleNamespace(run_ai_prompt=model)

        with patch.dict(sys.modules, {"tools": fake_tools}):
            selected = skill_registry.match_verified(
                "Please install a matching tactic for another team"
            )
        self.assertEqual(selected["id"], skill["id"])
        self.assertTrue(model.called)

        model.return_value = {
            "decision": "USE",
            "skill_id": "skill_invented",
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            self.assertIsNone(skill_registry.match_verified("use a skill"))

    def test_rejection_is_invalidated_and_never_saved_as_verified(self):
        candidate = self._candidate()
        self.assertTrue(
            skill_registry.discard_pending(
                candidate["id"], "User rejected the destination", user_rejected=True
            )
        )
        self.assertIsNone(skill_registry.load_pending(candidate["id"]))
        self.assertEqual(
            skill_registry._load_list(skill_registry.SKILLS_FILE), []
        )
        invalidated = skill_registry._load_list(
            skill_registry.INVALIDATED_FILE
        )
        self.assertEqual(invalidated[0]["status"], "user_rejected")


if __name__ == "__main__":
    unittest.main()
