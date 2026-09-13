import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_autonomy
import knowledge_worker


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


def topic(topic_id="akb48_ecosystem"):
    return {
        "topic_id": topic_id,
        "title": "AKB48",
        "aliases": ["AKB48 Group"],
        "classification": {},
        "lifecycle": {
            "state": "ACTIVE",
            "interest_score": 0.8,
            "next_focus": "group structure",
        },
    }


class SourceSelectionTests(unittest.TestCase):
    def test_approved_source_topic_match_is_case_insensitive(self):
        source = {
            "name": "AKB48 Official",
            "url": "https://www.akb48.co.jp/about/",
            "domain": "akb48.co.jp",
            "topics": ["akb48"],
            "status": "approved",
            "trust_score": 0.95,
        }
        with patch.object(
            knowledge_worker.knowledge,
            "load_sources",
            return_value=[source],
        ):
            self.assertEqual(knowledge_worker.choose_sources(["AKB48"]), [source])

    def test_primary_discovery_ranks_official_before_low_accountability(self):
        results = [
            {
                "title": "AKB48 Official roster mirror",
                "url": "https://grokipedia.com/akb48",
                "domain": "grokipedia.com",
                "description": "Unofficial summary",
            },
            {
                "title": "AKB48 公式サイト",
                "url": "https://www.akb48.co.jp/about/",
                "domain": "akb48.co.jp",
                "description": "公式情報",
            },
            {
                "title": "AKB48 history",
                "url": "https://www.britannica.com/topic/AKB48",
                "domain": "britannica.com",
                "description": "Reference",
            },
        ]
        added = []
        with (
            patch.object(knowledge_worker.tools, "search", return_value=results) as search,
            patch.object(knowledge_worker.knowledge, "load_source_candidates", return_value=[]),
            patch.object(
                knowledge_worker.knowledge,
                "add_source_candidate",
                side_effect=lambda result, topics: added.append(result["domain"]) or True,
            ),
        ):
            count = knowledge_worker.discover_source_candidates(
                ["AKB48"],
                ["AKB48 group structure", "AKB48"],
                phase="PRIMARY",
            )
        self.assertEqual(count, 3)
        self.assertEqual(added[0], "akb48.co.jp")
        self.assertEqual(added[-1], "grokipedia.com")
        self.assertIn("official site primary source", search.call_args.args[0])

    def test_fallback_uses_clean_title_and_avoids_attempted_domains(self):
        results = [
            {
                "title": "Attempted official",
                "url": "https://www.akb48.co.jp/other/",
                "domain": "akb48.co.jp",
            },
            {
                "title": "Established reporting",
                "url": "https://www.nhk.or.jp/akb48",
                "domain": "nhk.or.jp",
            },
        ]
        added = []
        with (
            patch.object(knowledge_worker.tools, "search", return_value=results) as search,
            patch.object(knowledge_worker.knowledge, "load_source_candidates", return_value=[]),
            patch.object(
                knowledge_worker.knowledge,
                "add_source_candidate",
                side_effect=lambda result, topics: added.append(result["domain"]) or True,
            ),
        ):
            count = knowledge_worker.discover_source_candidates(
                ["AKB48"],
                ["AKB48 group structure", "AKB48"],
                phase="FALLBACK",
                blocked_domains={"akb48.co.jp"},
            )
        self.assertEqual(count, 1)
        self.assertEqual(added, ["nhk.or.jp"])
        self.assertTrue(search.call_args.args[0].startswith("AKB48 "))
        self.assertIn("established reference", search.call_args.args[0])

    def test_source_read_error_is_backed_off_and_domain_attempted_once(self):
        candidates = [
            {
                "url": "https://example.org/one",
                "domain": "example.org",
                "topics": ["AKB48"],
                "status": "candidate",
            },
            {
                "url": "https://example.org/two",
                "domain": "example.org",
                "topics": ["AKB48"],
                "status": "candidate",
            },
        ]
        attempted_domains = set()
        with (
            patch.object(knowledge_worker.knowledge, "load_source_candidates", return_value=candidates),
            patch.object(knowledge_worker, "read_source", side_effect=RuntimeError("403")) as read,
            patch.object(knowledge_worker.knowledge, "record_source_candidate_failure") as record,
        ):
            counts = knowledge_worker.review_source_candidates(
                ["akb48"],
                attempted_urls=set(),
                attempted_domains=attempted_domains,
            )
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(attempted_domains, {"example.org"})
        record.assert_called_once()

    def test_future_retry_candidate_is_skipped(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        candidate = {
            "url": "https://example.org/one",
            "domain": "example.org",
            "topics": ["AKB48"],
            "status": "candidate",
            "retry_after": future,
        }
        with (
            patch.object(knowledge_worker.knowledge, "load_source_candidates", return_value=[candidate]),
            patch.object(knowledge_worker, "read_source") as read,
        ):
            counts = knowledge_worker.review_source_candidates(["AKB48"])
        self.assertEqual(counts, {
            "approved": 0, "pending": 0, "rejected": 0, "errors": 0
        })
        read.assert_not_called()

    def test_approved_official_stops_low_accountability_leftovers(self):
        candidates = [
            {
                "name": "AKB48 公式サイト",
                "url": "https://www.akb48.co.jp/about/",
                "domain": "akb48.co.jp",
                "topics": ["AKB48"],
                "status": "candidate",
            },
            {
                "name": "Community wiki",
                "url": "https://en.namu.wiki/akb48",
                "domain": "en.namu.wiki",
                "topics": ["AKB48"],
                "status": "candidate",
            },
        ]
        with (
            patch.object(knowledge_worker.knowledge, "load_source_candidates", return_value=candidates),
            patch.object(knowledge_worker, "read_source", return_value="official evidence" * 30) as read,
            patch.object(
                knowledge_worker.knowledge_ai,
                "judge_source",
                return_value={
                    "decision": "APPROVE",
                    "source_class": "official",
                    "trust_score": 0.95,
                    "reason": "Official organization page.",
                },
            ),
            patch.object(knowledge_worker.knowledge, "apply_source_judgment", return_value="APPROVE"),
        ):
            counts = knowledge_worker.review_source_candidates(["AKB48"])
        self.assertEqual(counts["approved"], 1)
        self.assertEqual(read.call_count, 1)


class SourceCandidateStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        data = Path(self.temporary.name) / "data"
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(data),
            KNOWLEDGE_FILE=str(data / "knowledge.json"),
            SOURCES_FILE=str(data / "knowledge_sources.json"),
            LOGS_FILE=str(data / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(data / "knowledge_source_candidates.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    def test_same_domain_can_keep_three_distinct_pages_not_four(self):
        values = []
        for index in range(4):
            values.append(knowledge.add_source_candidate(
                {
                    "title": "Page " + str(index),
                    "url": "https://example.org/page-" + str(index),
                },
                ["AKB48"],
            ))
        self.assertEqual(values, [True, True, True, False])
        self.assertEqual(len(knowledge.load_source_candidates()), 3)

    def test_read_failure_persists_retry_metadata(self):
        knowledge.add_source_candidate(
            {"title": "Official", "url": "https://example.org/official"},
            ["AKB48"],
        )
        candidate = knowledge.load_source_candidates()[0]
        self.assertTrue(knowledge.record_source_candidate_failure(
            candidate, "403 Client Error", retry_after_hours=24
        ))
        stored = knowledge.load_source_candidates()[0]
        self.assertEqual(stored["attempt_count"], 1)
        self.assertEqual(stored["last_attempt_status"], "READ_ERROR")
        self.assertIn("403", stored["last_error"])
        self.assertIsNotNone(knowledge_worker._parse_utc(stored["retry_after"]))

    def test_reapproval_extends_topics_on_existing_approved_source(self):
        candidate = {
            "name": "Official",
            "url": "https://example.org/official",
            "domain": "example.org",
            "topics": ["AKB48"],
        }
        knowledge.add_source_candidate(candidate, ["AKB48"])
        knowledge.apply_source_judgment(candidate, {
            "decision": "APPROVE",
            "source_class": "official",
            "trust_score": 0.95,
            "reason": "Official organization page.",
        })
        extension = dict(candidate, topics=["Manchester United"])
        knowledge.add_source_candidate(extension, ["Manchester United"])
        knowledge.apply_source_judgment(extension, {
            "decision": "APPROVE",
            "source_class": "official",
            "trust_score": 0.95,
            "reason": "Official organization page.",
        })
        source = next(
            item for item in knowledge.load_sources(False)
            if item.get("url") == candidate["url"]
        )
        self.assertEqual(
            {value.casefold() for value in source["topics"]},
            {"akb48", "manchester united"},
        )


class NoEvidenceOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)

    def no_evidence_log(self, age_hours=0, mode="OPEN_GAP"):
        return {
            "autonomy_contract_version": 1,
            "status": "COMPLETED",
            "selection_mode": mode,
            "selected_topic_ids": ["akb48_ecosystem"],
            "finished_at": (self.now - timedelta(hours=age_hours)).isoformat(),
            "verified": 0,
            "updated": 0,
            "duplicate": 0,
            "log_only": 0,
        }

    def test_old_zero_evidence_completion_is_normalized_without_rewrite(self):
        log = self.no_evidence_log()
        self.assertEqual(
            knowledge_autonomy.effective_run_status(log),
            "NO_VERIFIED_EVIDENCE",
        )
        self.assertFalse(knowledge_autonomy.is_successful_run(log))
        self.assertEqual(log["status"], "COMPLETED")

    def test_open_gap_no_evidence_retries_after_24_hours_not_seven_days(self):
        catalog = [topic()]
        waiting = knowledge_autonomy.build_plan(
            catalog, [], [self.no_evidence_log(23)], now=self.now
        )
        retry = knowledge_autonomy.build_plan(
            catalog, [], [self.no_evidence_log(25)], now=self.now
        )
        self.assertFalse(waiting["due"])
        self.assertEqual(waiting["mode"], "NOT_DUE")
        self.assertTrue(retry["due"])
        self.assertEqual(retry["selected_topic_ids"], ["akb48_ecosystem"])

    def test_failed_background_profile_does_not_loop_every_ten_minutes(self):
        log = self.no_evidence_log(2, mode="BACKGROUND_PROFILE")
        log["selected_topic_ids"] = []
        waiting = knowledge_autonomy.build_plan([], [], [log], now=self.now)
        retry = knowledge_autonomy.build_plan(
            [], [], [dict(log, finished_at=(self.now - timedelta(hours=25)).isoformat())],
            now=self.now,
        )
        self.assertFalse(waiting["due"])
        self.assertEqual(waiting["mode"], "NOT_DUE")
        self.assertTrue(retry["due"])
        self.assertEqual(retry["mode"], "BACKGROUND_PROFILE")

    def test_cycle_runs_fallback_and_reports_no_verified_evidence(self):
        plan = {
            "mode": "OPEN_GAP",
            "reason": "Open gap.",
            "selected_topic_ids": ["akb48_ecosystem"],
            "selected_topics": [topic()],
        }
        with (
            patch.object(knowledge_worker.knowledge, "initialize"),
            patch.object(knowledge_worker.knowledge, "load_items", return_value=[]),
            patch.object(knowledge_worker, "choose_sources", side_effect=[[], [], []]),
            patch.object(knowledge_worker, "discover_source_candidates", side_effect=[2, 1]) as discover,
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                side_effect=[
                    {"approved": 0, "pending": 0, "rejected": 1, "errors": 1},
                    {"approved": 0, "pending": 1, "rejected": 0, "errors": 0},
                ],
            ),
            patch.object(knowledge_worker, "organize_learned_knowledge", return_value={"status": "SKIPPED"}),
            patch.object(knowledge_worker.knowledge, "append_learning_log") as append,
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["AKB48"], autonomy_plan=plan, trigger="windows_scheduler"
            )
        self.assertEqual(discover.call_count, 2)
        self.assertEqual(log["status"], "NO_VERIFIED_EVIDENCE")
        self.assertEqual(log["source_candidates_discovered"], 3)
        self.assertEqual(log["source_discovery"]["fallback_added"], 1)
        self.assertEqual(log["verified_evidence_count"], 0)
        append.assert_called_once_with(log)

    def test_cycle_with_verified_claim_remains_completed(self):
        source = {
            "name": "AKB48 Official",
            "url": "https://www.akb48.co.jp/about/",
            "domain": "akb48.co.jp",
            "topics": ["AKB48"],
            "status": "approved",
        }
        plan = {
            "mode": "OPEN_GAP",
            "reason": "Open gap.",
            "selected_topic_ids": ["akb48_ecosystem"],
            "selected_topics": [topic()],
        }
        verified = {"claim": "AKB48 has an official group structure page."}
        with (
            patch.object(knowledge_worker.knowledge, "initialize"),
            patch.object(knowledge_worker.knowledge, "load_items", return_value=[]),
            patch.object(knowledge_worker, "choose_sources", return_value=[source]),
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                return_value={"approved": 0, "pending": 0, "rejected": 0, "errors": 0},
            ),
            patch.object(knowledge_worker, "read_source", return_value="official evidence" * 30),
            patch.object(knowledge_worker, "extract_candidates", return_value=[verified]),
            patch.object(knowledge_worker.knowledge_ai, "judge_knowledge", return_value={}),
            patch.object(
                knowledge_worker.knowledge,
                "apply_knowledge_judgment",
                return_value=("verified", verified),
            ),
            patch.object(knowledge_worker, "organize_learned_knowledge", return_value={"status": "SKIPPED"}),
            patch.object(knowledge_worker.knowledge, "append_learning_log"),
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["AKB48"], autonomy_plan=plan, trigger="windows_scheduler"
            )
        self.assertEqual(log["status"], "COMPLETED")
        self.assertEqual(log["verified_evidence_count"], 1)


class SourceRecoveryBuildTests(unittest.TestCase):
    def test_build_metadata_mirrors_and_docs(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Legacy Visual Evidence Backfill V1.10.54.8",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        for relative in (
            "knowledge.py", "knowledge_worker.py", "knowledge_autonomy.py",
            "knowledge_scheduler.py",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )
        self.assertTrue(
            (ROOT / "TEST_KNOWLEDGE_SOURCE_RECOVERY_V1_10_54_1.ps1").is_file()
        )
        self.assertTrue(
            (ROOT / "KNOWLEDGE_SOURCE_RECOVERY_V1_10_54_1_NOTES.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
