import json
import multiprocessing
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import knowledge
import sqlite_storage
from nerv import governance
from nerv.curiosity import CuriosityJournal
from nerv.learning_engine import LearningEngine
from nerv.profile_store import ProfileStore


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


def _append_process(root, worker, count):
    path = Path(root) / "data" / "nerv" / "learning_events.jsonl"
    for index in range(count):
        sqlite_storage.append_event(
            "nerv",
            "nerv/learning_events.jsonl",
            path,
            {"worker": worker, "index": index},
        )


class SQLiteSchemaV2Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()

    def test_v1_database_upgrades_in_place_and_keeps_existing_document(self):
        database = self.data / sqlite_storage.DATABASE_FILENAME
        payload = sqlite_storage._canonical_payload({"phase": 1})
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                """
                CREATE TABLE storage_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE json_documents (
                    namespace TEXT NOT NULL,
                    document_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, document_key)
                );
                CREATE TABLE json_migrations (
                    namespace TEXT NOT NULL,
                    document_key TEXT NOT NULL,
                    source_path TEXT,
                    backup_path TEXT,
                    source_sha256 TEXT NOT NULL,
                    migrated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, document_key)
                );
                PRAGMA user_version = 1;
                """
            )
            connection.execute(
                """
                INSERT INTO json_documents(
                    namespace, document_key, payload,
                    payload_sha256, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    "core_memory",
                    "task.json",
                    payload,
                    sqlite_storage._payload_digest({"phase": 1}),
                    "2026-09-02T00:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        nested = self.data / "knowledge" / "inbox.json"
        self.assertEqual(
            sqlite_storage.load_document(
                "knowledge",
                "knowledge/inbox.json",
                nested,
                {"items": []},
                migration_backup_suffix=(
                    sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
                ),
            ),
            {"items": []},
        )

        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                2,
            )
            self.assertEqual(
                json.loads(
                    connection.execute(
                        """
                        SELECT payload FROM json_documents
                        WHERE namespace = 'core_memory'
                          AND document_key = 'task.json'
                        """
                    ).fetchone()[0]
                ),
                {"phase": 1},
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        self.assertTrue(
            {"jsonl_streams", "jsonl_events", "jsonl_migrations"}.issubset(
                tables
            )
        )

    def test_nested_knowledge_and_nerv_paths_share_data_database(self):
        paths = (
            self.data / "knowledge.json",
            self.data / "knowledge" / "topics" / "snh48.json",
            self.data / "nerv" / "profile.json",
            self.data / "nerv" / "audit.jsonl",
        )
        expected = self.data / sqlite_storage.DATABASE_FILENAME
        self.assertTrue(
            all(sqlite_storage.database_path_for(path) == expected for path in paths)
        )
        self.assertEqual(
            sqlite_storage.document_key_for(paths[1]),
            "knowledge/topics/snh48.json",
        )
        self.assertEqual(
            sqlite_storage.document_key_for(paths[2]),
            "nerv/profile.json",
        )

    def test_jsonl_import_preserves_exact_source_and_rejects_bad_lines(self):
        path = self.data / "nerv" / "audit.jsonl"
        path.parent.mkdir(parents=True)
        raw = '{"event": "old", "value": 1}\nnot-json\n'
        path.write_text(raw, encoding="utf-8")

        self.assertTrue(
            sqlite_storage.append_event(
                "nerv",
                "nerv/audit.jsonl",
                path,
                {"event": "new", "value": 2},
            )
        )

        backup = Path(
            str(path) + sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        )
        self.assertEqual(backup.read_text(encoding="utf-8"), raw)
        mirror = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([item["event"] for item in mirror], ["old", "new"])
        connection = sqlite3.connect(self.data / sqlite_storage.DATABASE_FILENAME)
        try:
            migration = connection.execute(
                """
                SELECT valid_line_count, rejected_line_count
                FROM jsonl_migrations
                WHERE namespace = 'nerv' AND stream_key = 'nerv/audit.jsonl'
                """
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(migration, (1, 1))

    def test_missing_or_corrupt_jsonl_mirror_is_rebuilt_without_event_loss(self):
        path = self.data / "nerv" / "curiosity_audit.jsonl"
        sqlite_storage.append_event(
            "nerv",
            "nerv/curiosity_audit.jsonl",
            path,
            {"id": "committed"},
        )
        path.write_text("damaged-line\n", encoding="utf-8")
        future = time.time() + 2
        os.utime(path, (future, future))

        loaded = sqlite_storage.load_event_stream(
            "nerv",
            "nerv/curiosity_audit.jsonl",
            path,
        )

        self.assertEqual(loaded, [{"id": "committed"}])
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"id": "committed"},
        )
        self.assertEqual(
            Path(str(path) + ".bak").read_text(encoding="utf-8"),
            "damaged-line\n",
        )
        path.unlink()
        self.assertEqual(
            sqlite_storage.load_event_stream(
                "nerv",
                "nerv/curiosity_audit.jsonl",
                path,
            ),
            [{"id": "committed"}],
        )
        self.assertTrue(path.is_file())

    def test_rollback_version_append_is_merged_without_losing_newer_events(self):
        path = self.data / "nerv" / "learning_events.jsonl"
        for event_id in ("one", "two"):
            sqlite_storage.append_event(
                "nerv",
                "nerv/learning_events.jsonl",
                path,
                {"id": event_id},
            )
        path.write_text(
            json.dumps({"id": "one"})
            + "\n"
            + json.dumps({"id": "rollback-three"})
            + "\n",
            encoding="utf-8",
        )
        future = time.time() + 2
        os.utime(path, (future, future))

        sqlite_storage.append_event(
            "nerv",
            "nerv/learning_events.jsonl",
            path,
            {"id": "four"},
        )
        events = sqlite_storage.load_event_stream(
            "nerv",
            "nerv/learning_events.jsonl",
            path,
        )

        self.assertEqual(
            [event["id"] for event in events],
            ["one", "two", "rollback-three", "four"],
        )
        mirror = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(mirror, events)

    def test_unavailable_database_falls_back_to_jsonl(self):
        path = self.root / "audit.jsonl"
        (self.root / sqlite_storage.DATABASE_FILENAME).mkdir()
        saved = sqlite_storage.append_event(
            "nerv",
            "audit.jsonl",
            path,
            {"safe": True},
        )
        self.assertFalse(saved)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            {"safe": True},
        )

    def test_parallel_processes_append_without_loss_or_mirror_divergence(self):
        path = self.data / "nerv" / "learning_events.jsonl"
        sqlite_storage.load_event_stream(
            "nerv",
            "nerv/learning_events.jsonl",
            path,
        )
        process_context = multiprocessing.get_context("spawn")
        processes = [
            process_context.Process(
                target=_append_process,
                args=(str(self.root), worker, 6),
            )
            for worker in range(4)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
        self.assertEqual([process.exitcode for process in processes], [0] * 4)

        events = sqlite_storage.load_event_stream(
            "nerv",
            "nerv/learning_events.jsonl",
            path,
        )
        identities = {(event["worker"], event["index"]) for event in events}
        self.assertEqual(len(events), 24)
        self.assertEqual(len(identities), 24)
        mirror = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(mirror, events)
        connection = sqlite3.connect(self.data / sqlite_storage.DATABASE_FILENAME)
        try:
            self.assertEqual(
                connection.execute("PRAGMA quick_check").fetchone()[0],
                "ok",
            )
        finally:
            connection.close()


class SQLitePhaseTwoIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.knowledge_patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(self.data),
            KNOWLEDGE_FILE=str(self.data / "knowledge.json"),
            SOURCES_FILE=str(self.data / "knowledge_sources.json"),
            LOGS_FILE=str(self.data / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(
                self.data / "knowledge_source_candidates.json"
            ),
        )
        self.knowledge_patcher.start()
        self.addCleanup(self.knowledge_patcher.stop)

    def test_knowledge_documents_topics_and_backups_use_sqlite(self):
        self.data.mkdir()
        original = '[{"id":"legacy","status":"verified"}]\n'
        Path(knowledge.KNOWLEDGE_FILE).write_text(original, encoding="utf-8")

        knowledge.initialize()
        topic_path = Path(knowledge._topic_path("snh48"))
        topic_value = {"topic_id": "snh48", "items": [{"id": "night"}]}
        knowledge._save(topic_path, topic_value, backup=True)
        topic_path.unlink()
        self.assertEqual(knowledge._load(topic_path, {}), topic_value)

        backup = Path(
            knowledge.KNOWLEDGE_FILE
            + sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        )
        self.assertEqual(backup.read_text(encoding="utf-8"), original)
        connection = sqlite3.connect(self.data / sqlite_storage.DATABASE_FILENAME)
        try:
            keys = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT document_key FROM json_documents
                    WHERE namespace = 'knowledge'
                    """
                )
            }
        finally:
            connection.close()
        self.assertTrue(
            {
                "knowledge.json",
                "knowledge_sources.json",
                "learning_logs.json",
                "knowledge_source_candidates.json",
                "knowledge_clusters.json",
                "knowledge/inbox.json",
                "knowledge/index.json",
                "knowledge/conflicts.json",
                "knowledge/curator_runs.json",
                "knowledge/stable_review_runs.json",
                "knowledge/topics/snh48.json",
            }.issubset(keys)
        )

    def test_nerv_initializers_reconstruct_deleted_json_from_sqlite(self):
        profile_path = self.data / "nerv" / "profile.json"
        profile_path.parent.mkdir(parents=True)
        original_value = {
            "schema_version": 1,
            "revision": 7,
            "items": [{"status": "active", "key": "name", "value": "Bekki"}],
        }
        raw = json.dumps(original_value, ensure_ascii=False, indent=2) + "\n"
        profile_path.write_text(raw, encoding="utf-8")

        store = ProfileStore(base_dir=self.root)
        self.assertEqual(store.load(), original_value)
        profile_path.unlink()
        rebuilt = ProfileStore(base_dir=self.root)
        self.assertEqual(rebuilt.load(), original_value)
        self.assertEqual(json.loads(profile_path.read_text(encoding="utf-8")), original_value)
        self.assertEqual(
            Path(
                str(profile_path)
                + sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
            ).read_text(encoding="utf-8"),
            raw,
        )

        CuriosityJournal(lambda *_args, **_kwargs: {}, base_dir=self.root)
        LearningEngine(base_dir=self.root)
        connection = sqlite3.connect(self.data / sqlite_storage.DATABASE_FILENAME)
        try:
            identities = set(
                connection.execute(
                    """
                    SELECT namespace, document_key FROM json_documents
                    WHERE namespace = 'nerv'
                    """
                ).fetchall()
            )
        finally:
            connection.close()
        self.assertTrue(
            {
                ("nerv", "nerv/profile.json"),
                ("nerv", "nerv/curiosity.json"),
                ("nerv", "nerv/skills.json"),
            }.issubset(identities)
        )

    def test_root_and_casper_knowledge_modules_remain_identical(self):
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )

    def test_deferred_skill_and_personalization_stores_are_not_migrated(self):
        deferred = (
            "casper/skill_registry.py",
            "casper/application_skills.py",
            "emotion.py",
            "ui_preferences.py",
            "location.py",
            "video_sites.py",
        )
        for relative in deferred:
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertNotIn("import sqlite_storage", source)


class SQLitePhaseTwoPackagingTests(unittest.TestCase):
    def test_build_identity_schema_and_installer_contract(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["baseline"],
            "SQLite Knowledge + NERV Storage Phase 2 V1.10.49",
        )
        self.assertEqual(sqlite_storage.SCHEMA_VERSION, 2)
        self.assertIn(
            f'BEKKI_BUILD_ID = "{BUILD_ID}"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        installer = (ROOT / "INSTALL_STABLE_V1.ps1").read_text(
            encoding="utf-8"
        )
        for relative in (
            '"sqlite_storage.py"',
            '"knowledge.py"',
            '"casper\\knowledge.py"',
            '"nerv\\governance.py"',
            '"nerv\\profile_store.py"',
            '"nerv\\curiosity.py"',
            '"nerv\\topic_lifecycle.py"',
            '"nerv\\learning_engine.py"',
        ):
            with self.subTest(relative=relative):
                self.assertIn(relative, installer)
        self.assertTrue(
            (ROOT / "SQLITE_KNOWLEDGE_NERV_PHASE_2_V1_10_49_NOTES.md").is_file()
        )
        self.assertTrue(
            (
                ROOT
                / "KNOWLEDGE_AUTONOMY_TOPIC_LIFECYCLE_V1_10_50_NOTES.md"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
