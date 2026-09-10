import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_autonomy
import knowledge_scheduler
import knowledge_worker


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


def topic(topic_id, state, interest, next_focus=""):
    return {
        "topic_id": topic_id,
        "title": topic_id.replace("_", " "),
        "aliases": [],
        "classification": {},
        "lifecycle": {
            "state": state,
            "interest_score": interest,
            "next_focus": next_focus,
        },
    }


class UnifiedAutonomyPlanTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

    def test_due_refresh_outranks_higher_interest_open_gap(self):
        catalog = [
            topic("manchester_united", "PAUSED_COMPLETE", 0.6),
            topic("microduck", "ACTIVE", 1.0, "control software"),
        ]
        refresh = [{
            "topic_id": "manchester_united",
            "wake_reason": "REVIEW_DUE",
            "due_at": "2026-09-05T00:00:00+00:00",
        }]
        plan = knowledge_autonomy.build_plan(
            catalog, refresh, [], now=self.now
        )
        self.assertTrue(plan["due"])
        self.assertEqual(plan["mode"], "REVIEW_DUE")
        self.assertEqual(plan["selected_topic_ids"], ["manchester_united"])

    def test_highest_interest_active_topic_is_selected_once(self):
        catalog = [
            topic("manchester_united", "ACTIVE", 0.9, "club structure"),
            topic("microduck", "ACTIVE", 0.7, "control software"),
            topic("twice", "PAUSED_COMPLETE", 1.0),
        ]
        plan = knowledge_autonomy.build_plan(
            catalog, [], [], now=self.now
        )
        self.assertEqual(plan["mode"], "OPEN_GAP")
        self.assertEqual(plan["selected_topic_ids"], ["manchester_united"])
        self.assertEqual(
            len(plan["selected_topics"]),
            knowledge_autonomy.MAX_SELECTED_TOPICS,
        )

    def test_open_curiosity_and_paused_topic_are_not_duplicated(self):
        catalog = [
            topic("manchester_united", "ACTIVE", 1.0, "club structure"),
            topic("microduck", "ACTIVE", 0.7, "control software"),
            topic("twice", "PAUSED_COMPLETE", 0.9),
        ]
        recent = [{
            "status": "COMPLETED",
            "finished_at": self.now.isoformat(),
        }]
        plan = knowledge_autonomy.build_plan(
            catalog,
            [],
            recent,
            now=self.now,
            excluded_topic_ids=["manchester_united"],
        )
        self.assertEqual(plan["selected_topic_ids"], ["microduck"])

    def test_per_topic_cooldown_prevents_repeat_then_uses_fallback_clock(self):
        catalog = [topic("microduck", "ACTIVE", 0.7, "control software")]
        recent = [{
            "autonomy_contract_version": 1,
            "status": "COMPLETED",
            "finished_at": self.now.isoformat(),
            "selected_topic_ids": ["microduck"],
        }]
        plan = knowledge_autonomy.build_plan(
            catalog, [], recent, now=self.now
        )
        self.assertFalse(plan["due"])
        self.assertEqual(plan["mode"], "NOT_DUE")
        self.assertEqual(plan["selected_topic_ids"], [])

    def test_legacy_success_log_migrates_background_interval_without_rewrite(self):
        recent = [{
            "finished_at": (self.now - timedelta(days=2)).isoformat(),
            "topics": ["manchester united"],
        }]
        waiting = knowledge_autonomy.build_plan(
            [], [], recent, now=self.now, background_interval_days=30
        )
        forced = knowledge_autonomy.build_plan(
            [], [], recent, now=self.now, background_interval_days=30, force=True
        )
        self.assertEqual(waiting["mode"], "NOT_DUE")
        self.assertFalse(waiting["due"])
        self.assertEqual(forced["mode"], "BACKGROUND_PROFILE")
        self.assertTrue(forced["due"])

    def test_cycle_lock_fails_fast_for_second_trigger(self):
        with knowledge_autonomy.cycle_lock() as first:
            self.assertTrue(first)
            with knowledge_autonomy.cycle_lock() as second:
                self.assertFalse(second)


class UnifiedAutonomyStorageTests(unittest.TestCase):
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
        self.source = {
            "name": "Official source",
            "url": "https://example.org/official",
            "domain": "example.org",
            "status": "approved",
            "trust_score": 0.95,
        }

    def test_stable_and_reviewable_share_current_sqlite_ledger(self):
        stable_result, stable = knowledge.apply_knowledge_judgment(
            {"subject": "Manchester United", "claim": "The club was founded in 1878."},
            self.source,
            {
                "action": "AUTO_SAVE",
                "knowledge_type": "stable",
                "lifecycle_basis": "FIXED_HISTORY",
                "temporal_scope": {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": "1878",
                    "allow_previous_period": False,
                },
                "valid_for_days": None,
                "confidence": 0.95,
                "risk": "low",
                "reason": "Direct official history.",
            },
        )
        review_result, reviewable = knowledge.apply_knowledge_judgment(
            {"subject": "Example club", "claim": "Its current official roster contains eleven listed players."},
            self.source,
            {
                "action": "AUTO_SAVE",
                "knowledge_type": "reviewable",
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "valid_for_days": 90,
                "confidence": 0.94,
                "risk": "low",
                "reason": "Direct current official roster.",
            },
        )
        self.assertEqual(stable_result, "verified")
        self.assertEqual(review_result, "verified")
        self.assertIsNone(stable["expires_at"])
        self.assertIsNotNone(reviewable["expires_at"])
        self.assertEqual(reviewable["knowledge_type"], "reviewable")
        self.assertEqual(
            stable["partition_lifecycle_audit_version"],
            knowledge.PARTITION_LIFECYCLE_AUDIT_VERSION,
        )
        self.assertEqual(len(knowledge.load_items()), 2)

    def test_news_and_match_events_are_log_only(self):
        before = len(knowledge.load_items())
        result, event = knowledge.apply_knowledge_judgment(
            {"subject": "Manchester United", "claim": "The club won today's match."},
            self.source,
            {
                "action": "LOG_ONLY",
                "knowledge_type": "news",
                "lifecycle_basis": "TRANSIENT_CURRENT_STATE_OR_EVENT",
                "valid_for_days": None,
                "confidence": 0.95,
                "risk": "low",
                "reason": "Daily result.",
            },
        )
        self.assertEqual(result, "log_only")
        self.assertEqual(event["knowledge_type"], "news")
        self.assertEqual(len(knowledge.load_items()), before)


class UnifiedAutonomyWiringTests(unittest.TestCase):
    def test_profile_fallback_cannot_reopen_paused_or_curiosity_owned_topic(self):
        catalog = [
            topic("manchester_united", "PAUSED_COMPLETE", 0.9),
            topic("microduck", "ACTIVE", 0.8, "control software"),
        ]
        catalog[0]["title"] = "Manchester United"
        catalog[1]["title"] = "Microduck"
        with (
            patch.object(knowledge, "load_topic_catalog", return_value=catalog),
            patch.object(knowledge, "load_topic_refresh_candidates", return_value=[]),
            patch.object(knowledge_worker, "profile_context", return_value="{}"),
            patch.object(
                knowledge_worker.tools,
                "run_ai_prompt",
                return_value={
                    "topics": ["Manchester United", "Microduck", "new topic"]
                },
            ),
        ):
            selected = knowledge_worker.derive_topics(
                limit=3,
                excluded_topic_ids=["microduck"],
            )
        self.assertEqual(selected, ["new topic"])

    def test_scheduler_and_desktop_use_the_same_executor(self):
        with patch.object(
            knowledge_worker,
            "run_autonomy_cycle",
            return_value={"status": "SKIPPED", "reason": "not_due"},
        ) as run:
            self.assertEqual(knowledge_scheduler.run_if_due(), 0)
        run.assert_called_once_with(
            trigger="windows_scheduler",
            background_interval_days=30,
            force=False,
        )
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            'knowledge_worker.run_autonomy_cycle(trigger="desktop_idle")',
            source,
        )
        self.assertIn("def check_unified_knowledge_autonomy", source)
        self.assertIn(
            "knowledge_autonomy_timer.timeout.connect("
            "check_unified_knowledge_autonomy)",
            source,
        )

    def test_worker_records_shared_trigger_and_selected_topic(self):
        plan = {
            "contract_version": 1,
            "mode": "OPEN_GAP",
            "reason": "Highest-interest open gap.",
            "selected_topic_ids": ["manchester_united"],
            "selected_topics": [],
        }
        with (
            patch.object(knowledge_worker.knowledge, "initialize"),
            patch.object(knowledge_worker.knowledge, "load_items", return_value=[]),
            patch.object(knowledge_worker, "choose_sources", return_value=[]),
            patch.object(knowledge_worker, "discover_source_candidates", return_value=0),
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                return_value={"approved": 0, "pending": 0, "rejected": 0, "errors": 0},
            ),
            patch.object(knowledge_worker, "organize_learned_knowledge", return_value={"status": "SKIPPED"}),
            patch.object(knowledge_worker.knowledge, "append_learning_log") as append,
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["Manchester United"],
                autonomy_plan=plan,
                trigger="desktop_idle",
            )
        self.assertEqual(log["autonomy_contract_version"], 1)
        self.assertEqual(log["trigger"], "desktop_idle")
        self.assertEqual(log["selection_mode"], "OPEN_GAP")
        self.assertEqual(log["selected_topic_ids"], ["manchester_united"])
        append.assert_called_once_with(log)

    def test_build_identity_prompts_and_mirrors(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Autonomous Visual Evidence V1.10.54.6",
        )
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "knowledge_worker.py").read_bytes(),
            (ROOT / "casper" / "knowledge_worker.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "knowledge_scheduler.py").read_bytes(),
            (ROOT / "casper" / "knowledge_scheduler.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "knowledge_autonomy.py").read_bytes(),
            (ROOT / "casper" / "knowledge_autonomy.py").read_bytes(),
        )
        judge_prompt = (ROOT / "prompts" / "knowledge_judge.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("stable | reviewable | event | news", judge_prompt)
        self.assertIn("MAINTAINED_SET_OR_STRUCTURE", judge_prompt)
        self.assertTrue(
            (ROOT / "TEST_UNIFIED_KNOWLEDGE_AUTONOMY_V1_10_54.ps1").is_file()
        )
        self.assertTrue(
            (ROOT / "UNIFIED_KNOWLEDGE_AUTONOMY_V1_10_54_NOTES.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
