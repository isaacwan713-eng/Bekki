import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import context
import history
import memory
import sqlite_storage
import tasks


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class SQLiteStorageFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_first_read_migrates_json_and_preserves_exact_backup(self):
        path = self.root / "profile.json"
        raw = '{\n  "name": "小贝",\n  "likes": ["夜蝶"]\n}\n'
        path.write_text(raw, encoding="utf-8")

        result = sqlite_storage.load_document(
            "core_memory",
            "profile.json",
            path,
            {},
        )

        self.assertEqual(result["likes"], ["夜蝶"])
        backup = Path(str(path) + sqlite_storage.MIGRATION_BACKUP_SUFFIX)
        self.assertEqual(backup.read_text(encoding="utf-8"), raw)
        self.assertTrue((self.root / sqlite_storage.DATABASE_FILENAME).is_file())
        status = sqlite_storage.storage_status(path)
        self.assertEqual(status["quick_check"], "ok")
        self.assertEqual(status["documents"], 1)
        self.assertEqual(status["migrations"], 1)

    def test_migration_is_idempotent_and_does_not_replace_first_backup(self):
        path = self.root / "pending.json"
        original = {"step": 1}
        path.write_text(json.dumps(original), encoding="utf-8")
        sqlite_storage.load_document("core_memory", "pending.json", path, {})
        backup = Path(str(path) + sqlite_storage.MIGRATION_BACKUP_SUFFIX)
        preserved = backup.read_bytes()

        sqlite_storage.save_document(
            "core_memory",
            "pending.json",
            path,
            {"step": 2},
        )
        sqlite_storage.load_document("core_memory", "pending.json", path, {})

        self.assertEqual(backup.read_bytes(), preserved)
        connection = sqlite3.connect(self.root / sqlite_storage.DATABASE_FILENAME)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM json_migrations"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1)

    def test_corrupt_or_missing_json_mirror_is_rebuilt_from_sqlite(self):
        path = self.root / "tasks.json"
        expected = {"version": 1, "tasks": [{"id": "safe"}]}
        sqlite_storage.save_document("task_manager", "tasks", path, expected)
        path.write_text('{"tasks": [', encoding="utf-8")

        recovered = sqlite_storage.load_document(
            "task_manager",
            "tasks",
            path,
            {},
        )

        self.assertEqual(recovered, expected)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)
        path.unlink()
        self.assertEqual(
            sqlite_storage.load_document("task_manager", "tasks", path, {}),
            expected,
        )
        self.assertTrue(path.is_file())

    def test_json_changed_by_rollback_version_is_reimported(self):
        path = self.root / "chat_history.json"
        initial = {"version": 6, "sessions": [{"id": "new"}]}
        rollback_edit = {"version": 6, "sessions": [{"id": "old-app-edit"}]}
        sqlite_storage.save_document(
            "conversation",
            "chat_history",
            path,
            initial,
        )
        path.write_text(
            json.dumps(rollback_edit, ensure_ascii=False),
            encoding="utf-8",
        )

        result = sqlite_storage.load_document(
            "conversation",
            "chat_history",
            path,
            {},
        )

        self.assertEqual(result, rollback_edit)
        connection = sqlite3.connect(self.root / sqlite_storage.DATABASE_FILENAME)
        try:
            payload = connection.execute(
                """
                SELECT payload FROM json_documents
                WHERE namespace = 'conversation'
                  AND document_key = 'chat_history'
                """
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(json.loads(payload), rollback_edit)

    def test_sqlite_commit_newer_than_stale_mirror_wins_after_crash(self):
        path = self.root / "tasks.json"
        old_value = {"version": 1, "tasks": [{"id": "old"}]}
        committed_value = {"version": 1, "tasks": [{"id": "committed"}]}
        sqlite_storage.save_document(
            "task_manager",
            "tasks",
            path,
            old_value,
        )
        payload = sqlite_storage._canonical_payload(committed_value)
        digest = sqlite_storage._payload_digest(committed_value)
        future = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        connection = sqlite3.connect(self.root / sqlite_storage.DATABASE_FILENAME)
        try:
            connection.execute(
                """
                UPDATE json_documents
                SET payload = ?, payload_sha256 = ?, updated_at = ?
                WHERE namespace = 'task_manager' AND document_key = 'tasks'
                """,
                (payload, digest, future),
            )
            connection.commit()
        finally:
            connection.close()

        result = sqlite_storage.load_document(
            "task_manager",
            "tasks",
            path,
            {},
        )

        self.assertEqual(result, committed_value)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), committed_value)

    def test_parallel_writers_leave_sqlite_and_json_at_same_generation(self):
        path = self.root / "temporary.json"
        barrier = threading.Barrier(12)
        errors = []

        def write(index):
            try:
                barrier.wait()
                sqlite_storage.save_document(
                    "core_memory",
                    "temporary.json",
                    path,
                    [{"writer": index}],
                )
            except Exception as error:  # pragma: no cover - assertion below
                errors.append(error)

        threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(errors)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        mirror = json.loads(path.read_text(encoding="utf-8"))
        stored = sqlite_storage.load_document(
            "core_memory",
            "temporary.json",
            path,
            [],
        )
        self.assertEqual(stored, mirror)

    def test_unavailable_database_fails_open_to_json(self):
        path = self.root / "pending.json"
        database_path = self.root / sqlite_storage.DATABASE_FILENAME
        database_path.mkdir()
        path.write_text('{"safe": true}', encoding="utf-8")

        self.assertEqual(
            sqlite_storage.load_document("core_memory", "pending.json", path, {}),
            {"safe": True},
        )
        saved = sqlite_storage.save_document(
            "core_memory",
            "pending.json",
            path,
            {"safe": "updated"},
        )
        self.assertFalse(saved)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"safe": "updated"},
        )


class SQLitePhaseOneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(context.set_active_session, None)

    def test_memory_history_tasks_and_context_share_one_database(self):
        profile_path = self.root / "profile.json"
        profile = {
            "profile": [{"content": "名字是小贝"}],
            "preference": [],
            "relationships": [],
        }
        profile_path.write_text(
            json.dumps(profile, ensure_ascii=False),
            encoding="utf-8",
        )
        memory_paths = {
            "DATA_FOLDER": str(self.root),
            "TEMPORARY_FILE": str(self.root / "temporary.json"),
            "TASK_FILE": str(self.root / "task.json"),
            "PROFILE_FILE": str(profile_path),
            "PENDING_FILE": str(self.root / "pending.json"),
        }

        with patch.multiple(memory, **memory_paths), patch.object(
            history,
            "_history_path",
            return_value=str(self.root / "chat_history.json"),
        ), patch.object(
            tasks,
            "_tasks_path",
            return_value=str(self.root / "tasks.json"),
        ), patch.object(context, "_data_dir", return_value=self.root):
            memory_data = memory.initialize_memory()
            history_data = history.load_history()
            task_data = tasks.load_tasks()
            context.set_active_session("session-one", migrate_legacy=True)
            context.save_context({"current_topic": "夜蝶"})

        self.assertEqual(memory_data["profile"], profile)
        self.assertTrue(history_data["sessions"])
        self.assertEqual(task_data, {"version": 1, "tasks": []})
        database_path = self.root / sqlite_storage.DATABASE_FILENAME
        connection = sqlite3.connect(database_path)
        try:
            identities = set(
                connection.execute(
                    "SELECT namespace, document_key FROM json_documents"
                ).fetchall()
            )
        finally:
            connection.close()
        self.assertTrue(
            {
                ("core_memory", "profile.json"),
                ("core_memory", "temporary.json"),
                ("core_memory", "task.json"),
                ("core_memory", "pending.json"),
                ("conversation", "chat_history"),
                ("task_manager", "tasks"),
                ("conversation_context", "legacy"),
                ("conversation_context", "session:session-one"),
            }.issubset(identities)
        )

    def test_deleted_session_context_is_removed_from_both_stores(self):
        with patch.object(context, "_data_dir", return_value=self.root):
            context.set_active_session("delete-me")
            context.save_context({"current_topic": "temporary"})
            context.delete_session_context("delete-me")

        legacy_path = self.root / "contexts" / "delete-me.json"
        self.assertFalse(legacy_path.exists())
        connection = sqlite3.connect(self.root / sqlite_storage.DATABASE_FILENAME)
        try:
            row = connection.execute(
                """
                SELECT 1 FROM json_documents
                WHERE namespace = 'conversation_context'
                  AND document_key = 'session:delete-me'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(row)


class SQLitePhaseOnePackagingTests(unittest.TestCase):
    def test_build_identity_and_installer_include_storage_foundation(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["baseline"],
            "SQLite Knowledge + NERV Storage Phase 2 V1.10.49",
        )
        self.assertIn(
            f'BEKKI_BUILD_ID = "{BUILD_ID}"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        installer = (ROOT / "INSTALL_STABLE_V1.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('"sqlite_storage.py"', installer)
        self.assertIn('"memory.py"', installer)
        self.assertIn('"history.py"', installer)
        self.assertIn('"tasks.py"', installer)
        self.assertIn('"context.py"', installer)

    def test_migrated_modules_use_sqlite_and_deferred_stores_do_not(self):
        for relative in (
            "memory.py",
            "history.py",
            "tasks.py",
            "context.py",
            "knowledge.py",
            "nerv/governance.py",
        ):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("import sqlite_storage", source)
        for relative in (
            "emotion.py",
            "ui_preferences.py",
            "location.py",
        ):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("import sqlite_storage", source)


if __name__ == "__main__":
    unittest.main()
