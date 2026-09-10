from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
from nerv import external_fact_fallback


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class CurrentRosterLifecycleNormalizationV110519Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name) / "data"
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(root),
            KNOWLEDGE_FILE=str(root / "knowledge.json"),
            SOURCES_FILE=str(root / "knowledge_sources.json"),
            LOGS_FILE=str(root / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(
                root / "knowledge_source_candidates.json"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    @staticmethod
    def _assessment():
        return {
            "decision": "ASK",
            "importance": "LOW",
            "sharing_risk": "NORMAL",
            "has_reusable_component": True,
        }

    @staticmethod
    def _partition(*, directly_supported=True):
        return {
            "answer_usable": True,
            "directly_answers": True,
            "complete_for_request": True,
            "claims": [{
                "persist": False,
                "directly_supported_by_answer": directly_supported,
                "no_evidence_conflict": True,
                "subject": "四禧丸子",
                "claim": (
                    "四禧丸子目前的四位成员是："
                    "恬豆、梨安、沐霂、又一。"
                ),
                "knowledge_type": "changing",
                "valid_for_days": None,
                "confidence": 1.0,
                "topics": ["四禧丸子"],
                "knowledge_domain": "culture_entertainment",
                "cluster_label": "entertainment_group_membership",
                "reason": "Current roster proposed as transient.",
            }],
            "reason": "One current-roster claim.",
        }

    @staticmethod
    def _incorrect_stable_audit():
        return {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "The complete roster is a maintained set.",
            }],
            "reason": "Model left the JSON lifecycle labels stable/null.",
        }

    @staticmethod
    def _candidate(claim=None):
        return {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "四禧丸子",
            "claim": claim or (
                "四禧丸子目前的四位成员是："
                "恬豆、梨安、沐霂、又一。"
            ),
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 365,
            "confidence": 1.0,
            "topics": ["四禧丸子", "成员名单"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "entertainment_group_membership",
            "reason": "Accepted current roster evidence.",
            "lifecycle_audit_status": "PASSED",
            "partition_lifecycle_audit_version": 10,
            "current_people_roster": True,
            "current_roster_lifecycle_normalization_version": 1,
        }

    @staticmethod
    def _source_context():
        return {
            "sources": [{
                "title": "Current roster result",
                "url": "https://example.test/current-roster",
                "domain": "example.test",
            }],
            "source_domain": "example.test",
            "source_name": "Current roster result",
            "verification_level": "casper_fact_lookup_knowledge_intake",
            "verification_status": "AI_PARTITIONED_AUDITED_FACT_LOOKUP",
        }

    def test_build_and_normalization_contract(self):
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))
        self.assertEqual(
            external_fact_fallback.CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION,
            1,
        )
        self.assertEqual(
            knowledge.CURRENT_ROSTER_LIFECYCLE_NORMALIZATION_VERSION,
            1,
        )
        self.assertEqual(
            external_fact_fallback.CURRENT_PEOPLE_ROSTER_REVIEW_DAYS,
            knowledge.CURRENT_PEOPLE_ROSTER_REVIEW_DAYS,
        )

    def test_model_stable_null_roster_is_normalized_without_retry(self):
        with patch(
            "tools.run_ai_prompt",
            return_value=self._incorrect_stable_audit(),
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.audit_partition_lifecycles(
                "四禧丸子现在的四位成员是谁？",
                "四禧丸子目前的四位成员是：恬豆、梨安、沐霂、又一。",
                {"results": []},
                self._assessment(),
                self._partition(),
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["lifecycle_audit_status"], "PASSED")
        claim = result["claims"][0]
        self.assertIs(claim["persist"], True)
        self.assertEqual(claim["knowledge_type"], "reviewable")
        self.assertEqual(
            claim["lifecycle_basis"], "MAINTAINED_SET_OR_STRUCTURE"
        )
        self.assertEqual(claim["valid_for_days"], 365)
        self.assertIs(claim["current_people_roster"], True)
        self.assertEqual(
            claim["current_roster_lifecycle_normalization_version"], 1
        )

    def test_normalization_never_promotes_ineligible_roster(self):
        with patch(
            "tools.run_ai_prompt",
            return_value=self._incorrect_stable_audit(),
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.audit_partition_lifecycles(
                "四禧丸子现在的四位成员是谁？",
                "没有直接支持名单的回答。",
                {"results": []},
                self._assessment(),
                self._partition(directly_supported=False),
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["lifecycle_audit_status"], "PASSED")
        self.assertIs(result["claims"][0]["persist"], False)
        self.assertEqual(result["claims"][0]["knowledge_type"], "reviewable")

    def test_live_intake_shape_refreshes_existing_roster_end_to_end(self):
        now = datetime.now(timezone.utc)
        original_claim = "官方公开的成员名单为：沐霂、又一、梨安、恬豆。"
        original_id = knowledge.make_id("四禧丸子", original_claim)
        knowledge._save_knowledge([{
            "id": original_id,
            "subject": "四禧丸子",
            "claim": original_claim,
            "topics": ["四禧丸子", "成员名单"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "entertainment_group_membership",
            "learned_at": (now - timedelta(days=10)).isoformat(),
            "confidence": 1.0,
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 30,
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "risk": "low",
            "status": "verified",
            "curation": {
                "status": "curated",
                "topic_id": "sihixian_ecosystem",
                "relationship_ids": ["r1", "r2", "r3", "r4"],
            },
        }])
        answer = "四禧丸子目前的四位成员是：恬豆、梨安、沐霂、又一。"
        search_result = {
            "status": "OK",
            "query": "四禧丸子 成员名单",
            "direct_reply": answer,
            "answers": [{
                "accepted": True,
                "answer": answer,
                "answer_status": "ACCEPTED",
                "temporal_validation": {
                    "time_scope_match": True,
                    "source_period": "current active state as of 2026-09-04",
                },
            }],
            "results": [{
                "title": "Current roster result",
                "url": "https://example.test/current-roster",
                "domain": "example.test",
            }],
        }

        with patch(
            "tools.run_ai_prompt",
            side_effect=[self._partition(), self._incorrect_stable_audit()],
        ) as model, patch("tools.unload_model"):
            result = external_fact_fallback.intake_audited_fact_lookup(
                "四禧丸子现在的四位成员是谁？",
                answer,
                search_result,
            )

        self.assertEqual(model.call_count, 2)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["claim_statuses"], ["updated"])
        self.assertEqual(result["knowledge_ids"], [original_id])
        stored = knowledge.load_items()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["id"], original_id)
        self.assertEqual(stored[0]["curation"]["relationship_ids"], [
            "r1", "r2", "r3", "r4",
        ])
        self.assertEqual(
            stored[0]["current_roster_lifecycle_normalization_version"], 1
        )
        self.assertEqual(
            stored[0]["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(stored[0]["current_roster_review"]["refresh_count"], 1)

    def test_same_member_set_refreshes_existing_claim_and_curation(self):
        now = datetime.now(timezone.utc)
        original_claim = "官方公开的成员名单为：沐霂、又一、梨安、恬豆。"
        original_id = knowledge.make_id("四禧丸子", original_claim)
        original = {
            "id": original_id,
            "subject": "四禧丸子",
            "claim": original_claim,
            "topics": ["四禧丸子", "成员名单"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "entertainment_group_membership",
            "source_url": "https://www.bilibili.com/video/BV1official",
            "source_domain": "bilibili.com",
            "source_name": "四禧丸子官方资料",
            "sources": [{
                "title": "四禧丸子官方资料",
                "url": "https://www.bilibili.com/video/BV1official",
                "domain": "bilibili.com",
            }],
            "learned_at": (now - timedelta(days=30)).isoformat(),
            "confidence": 1.0,
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 30,
            "expires_at": (now + timedelta(days=30)).isoformat(),
            "risk": "low",
            "status": "verified",
            "curation": {
                "status": "curated",
                "topic_id": "sihixian_ecosystem",
                "subject_entity_id": "sihixian_maruko",
                "relationship_ids": ["relation_member_one"],
                "related_entity_ids": ["member_one"],
            },
        }
        knowledge._save_knowledge([original])

        status, refreshed = knowledge.apply_external_ai_partitioned_claim(
            user_request="四禧丸子现在的四位成员是谁？",
            answer="四禧丸子目前的四位成员是：恬豆、梨安、沐霂、又一。",
            assessment=self._assessment(),
            candidate=self._candidate(),
            source_context=self._source_context(),
        )

        stored = knowledge.load_items()
        self.assertEqual(status, "updated")
        self.assertEqual(len(stored), 1)
        self.assertEqual(refreshed["id"], original_id)
        self.assertEqual(refreshed["claim"], original_claim)
        self.assertEqual(
            refreshed["curation"]["relationship_ids"],
            ["relation_member_one"],
        )
        self.assertEqual(refreshed["current_roster_review"]["refresh_count"], 1)
        self.assertEqual(
            refreshed["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(
            refreshed["current_roster_review"]["matched_member_count"], 4
        )
        self.assertGreater(
            datetime.fromisoformat(refreshed["expires_at"]),
            now + timedelta(days=360),
        )
        self.assertEqual(len(refreshed["sources"]), 2)
        self.assertEqual(
            refreshed["revision_history"][-1]["event"],
            "CURRENT_ROSTER_REVERIFIED",
        )

    def test_changed_member_set_cannot_overwrite_existing_roster(self):
        now = datetime.now(timezone.utc)
        original_claim = "官方公开的成员名单为：沐霂、又一、梨安、恬豆。"
        original_id = knowledge.make_id("四禧丸子", original_claim)
        original = {
            "id": original_id,
            "subject": "四禧丸子",
            "claim": original_claim,
            "topics": ["四禧丸子"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "entertainment_group_membership",
            "learned_at": now.isoformat(),
            "confidence": 1.0,
            "knowledge_type": "reviewable",
            "valid_for_days": 365,
            "expires_at": (now + timedelta(days=365)).isoformat(),
            "risk": "low",
            "status": "verified",
        }
        knowledge._save_knowledge([original])
        changed_claim = "四禧丸子目前的成员名单为：恬豆、梨安、沐霂、新成员。"

        status, created = knowledge.apply_external_ai_partitioned_claim(
            user_request="四禧丸子现在的成员是谁？",
            answer=changed_claim,
            assessment=self._assessment(),
            candidate=self._candidate(claim=changed_claim),
            source_context=self._source_context(),
        )

        stored = knowledge.load_items()
        self.assertEqual(status, "verified")
        self.assertEqual(len(stored), 2)
        self.assertNotEqual(created["id"], original_id)
        self.assertEqual(
            next(item for item in stored if item["id"] == original_id)["claim"],
            original_claim,
        )

    def test_closed_historical_roster_is_never_a_refresh_target(self):
        now = datetime.now(timezone.utc)
        historical_claim = "四禧丸子成员名单为：沐霂、又一、梨安、恬豆。"
        historical_scope = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "2022-01-15",
            "allow_previous_period": False,
            "closed_period": True,
        }
        historical_id = knowledge.make_id(
            "四禧丸子", historical_claim, historical_scope
        )
        knowledge._save_knowledge([{
            "id": historical_id,
            "subject": "四禧丸子",
            "claim": historical_claim,
            "topics": ["四禧丸子"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "entertainment_group_membership",
            "learned_at": now.isoformat(),
            "confidence": 1.0,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "temporal_scope": historical_scope,
        }])

        status, created = knowledge.apply_external_ai_partitioned_claim(
            user_request="四禧丸子现在的四位成员是谁？",
            answer="四禧丸子目前的四位成员是：恬豆、梨安、沐霂、又一。",
            assessment=self._assessment(),
            candidate=self._candidate(),
            source_context=self._source_context(),
        )

        stored = knowledge.load_items()
        self.assertEqual(status, "verified")
        self.assertEqual(len(stored), 2)
        self.assertNotEqual(created["id"], historical_id)
        historical = next(
            item for item in stored if item["id"] == historical_id
        )
        self.assertEqual(historical["knowledge_type"], "stable")
        self.assertTrue(historical["temporal_scope"]["closed_period"])


if __name__ == "__main__":
    unittest.main()
