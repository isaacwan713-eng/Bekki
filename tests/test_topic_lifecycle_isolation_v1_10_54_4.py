import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
from nerv.curiosity import CuriosityJournal
from nerv.knowledge_curator import KnowledgeCurator
from nerv.topic_lifecycle import (
    MAX_TOPIC_LIFECYCLE_INPUT_BYTES,
    TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION,
    TOPIC_LIFECYCLE_PLAN_SCHEMA,
    TopicLifecycleManager,
)


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class TopicLifecycleIsolationV110544Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        data = self.project / "data"
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

    @staticmethod
    def _item(item_id, subject, claim=None):
        return {
            "id": item_id,
            "subject": subject,
            "claim": claim or (subject + " has verified public background."),
            "topics": [subject],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": subject,
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.95,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
            "provenance": {"origin": "knowledge_worker"},
        }

    @staticmethod
    def _assignment(item, topic_id):
        return {
            "knowledge_id": item["id"],
            "decision": "STORE",
            "topic_id": topic_id,
            "topic_title": item["subject"],
            "topic_aliases": [],
            "topic_keywords": [item["subject"]],
            "subject_entity": {
                "id": topic_id + "_subject",
                "name": item["subject"],
                "type": "subject",
                "aliases": [],
            },
            "literal_claim_subject": item["subject"],
            "selected_subject_entity_id": topic_id + "_subject",
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "The verified claim names this subject.",
            "related_entities": [],
            "facet": "public_background",
            "claim_keywords": [item["subject"]],
            "preferred_display_claim": item["claim"],
            "preferred_display_language": "source",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "Store in the exact subject ecosystem.",
        }

    def _create_topic(self, topic_id, item):
        knowledge._save_knowledge(knowledge.load_items() + [item])
        result = knowledge.apply_curator_assignments([
            self._assignment(item, topic_id)
        ])
        self.assertEqual(result["curated"], 1)
        return knowledge.load_topic_lifecycle_assessment_candidates(
            preferred_topic_ids=[topic_id],
            include_topic_ids=[topic_id],
            limit=1,
        )[0]

    @staticmethod
    def _coverage(claim_ids, active=False):
        return [
            {
                "layer": layer,
                "status": (
                    "COVERED" if layer == "L1_FOUNDATION"
                    else "MISSING" if active and layer == "L2_CONTEXT"
                    else "NOT_NEEDED"
                ),
                "required_for_current_goal": (
                    layer == "L1_FOUNDATION"
                    or (active and layer == "L2_CONTEXT")
                ),
                "evidence_claim_ids": (
                    claim_ids if layer == "L1_FOUNDATION" else []
                ),
                "reason": "Coverage uses only the supplied claim IDs.",
            }
            for layer in knowledge.KNOWLEDGE_LAYERS
        ]

    @classmethod
    def _assessment(cls, candidate, *, active=False, interest=0.7):
        claim_ids = [
            value["knowledge_id"] for value in candidate.get("claims", [])
        ]
        return {
            "assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "assessment_fingerprint": candidate["assessment_fingerprint"],
            "topic_id": candidate["topic_id"],
            "claim_layers": [
                {
                    "knowledge_id": knowledge_id,
                    "knowledge_layer": "L1_FOUNDATION",
                    "reason": "This claim supplies the basic identity context.",
                }
                for knowledge_id in candidate.get(
                    "pending_layer_claim_ids", []
                )
            ],
            "topic_classification": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domain": "culture_entertainment",
                "category_path": [
                    {"id": "public_culture", "label": "public culture"},
                    {"id": "public_topics", "label": "public topics"},
                ],
                "reason": "This is reusable public cultural knowledge.",
            },
            "claim_classifications": [
                {
                    "knowledge_id": knowledge_id,
                    "fact_type": "IDENTITY_DEFINITION",
                    "reason": "The claim provides identifying background.",
                }
                for knowledge_id in candidate.get(
                    "pending_classification_claim_ids", []
                )
            ],
            "target_layer": "L2_CONTEXT" if active else "L1_FOUNDATION",
            "coverage": cls._coverage(claim_ids, active=active),
            "completion_score": 0.62 if active else 0.9,
            "confidence": 0.94,
            "state": "ACTIVE" if active else "PAUSED_COMPLETE",
            "next_focus": "Add one different context facet." if active else "",
            "pause_reason": "The present goal is covered." if not active else "",
            "interest_score": interest,
            "interest_basis": "The bounded signals set current priority.",
            "refresh_after_days": None if active else 90,
            "reason": "The state follows verified coverage.",
        }

    def test_schema_binds_contract_and_exact_snapshot(self):
        candidate = self._create_topic(
            "topic_alpha",
            self._item("knowledge_alpha", "Topic Alpha"),
        )
        schema = TopicLifecycleManager._schema_for(candidate)
        self.assertIn("assessment_contract_version", schema["required"])
        self.assertIn("assessment_fingerprint", schema["required"])
        self.assertEqual(
            schema["properties"]["assessment_fingerprint"]["enum"],
            [candidate["assessment_fingerprint"]],
        )

    def test_wrong_primary_fingerprint_uses_fresh_recovery(self):
        candidate = self._create_topic(
            "topic_recovery",
            self._item("knowledge_recovery", "Topic Recovery"),
        )
        calls = []

        def model(prompt, payload, **_kwargs):
            packet = json.loads(payload)
            calls.append((prompt, packet))
            plan = self._assessment(packet["topic"])
            if len(calls) == 1:
                plan["assessment_fingerprint"] = "0" * 64
            return plan

        result = TopicLifecycleManager(model).run_once(
            preferred_topic_ids=["topic_recovery"],
            only_topic_ids=["topic_recovery"],
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["primary_valid"], 0)
        self.assertEqual(result["recovered_valid"], 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("assessment_fingerprint_mismatch", calls[1][1]["contract_errors"])
        self.assertNotIn("invalid_first_assessment", calls[1][1])
        self.assertIn("intentionally absent", calls[1][1]["recovery_mode"])

    def test_stale_topic_snapshot_fails_before_any_write(self):
        candidate = self._create_topic(
            "topic_stale",
            self._item("knowledge_stale", "Topic Stale"),
        )
        plan = self._assessment(candidate)
        before = knowledge.load_topic_document("topic_stale")
        changed = deepcopy(before)
        changed["topic"]["title"] = "Topic Stale Updated"
        knowledge._save(knowledge._topic_path("topic_stale"), changed)

        with self.assertRaisesRegex(
            ValueError, "topic_lifecycle_assessment_snapshot_stale"
        ):
            knowledge.apply_topic_lifecycle_assessment(plan)

        after = knowledge.load_topic_document("topic_stale")
        self.assertEqual(after, changed)
        self.assertNotIn(
            "knowledge_layer", after["claims"][0].get("curation", {})
        )

    def test_one_failed_topic_does_not_block_the_next_topic(self):
        self._create_topic(
            "bad_topic",
            self._item("knowledge_bad", "Bad Topic"),
        )
        self._create_topic(
            "good_topic",
            self._item("knowledge_good", "Good Topic"),
        )

        def model(_prompt, payload, **_kwargs):
            candidate = json.loads(payload)["topic"]
            plan = self._assessment(candidate)
            if candidate["topic_id"] == "bad_topic":
                plan["assessment_fingerprint"] = "f" * 64
            return plan

        result = TopicLifecycleManager(model).run_once()

        self.assertEqual(result["status"], "COMPLETED_WITH_ERRORS")
        self.assertEqual(result["assessed"], 1)
        self.assertEqual(result["primary_valid"], 1)
        self.assertEqual(result["recovered_valid"], 0)
        self.assertEqual(result["failures"][0]["topic_id"], "bad_topic")
        self.assertNotIn(
            "knowledge_layer",
            knowledge.load_topic_document("bad_topic")["claims"][0][
                "curation"
            ],
        )
        self.assertEqual(
            knowledge.load_topic_document("good_topic")["claims"][0][
                "curation"
            ]["knowledge_layer"],
            "L1_FOUNDATION",
        )

    def test_restricted_run_does_not_assess_or_seed_another_topic(self):
        allowed = self._create_topic(
            "allowed_topic",
            self._item("knowledge_allowed", "Allowed Topic"),
        )
        other = self._create_topic(
            "other_topic",
            self._item("knowledge_other", "Other Topic"),
        )
        other_plan = self._assessment(other, interest=0.99)
        other_plan["_interest_fingerprint"] = (
            TopicLifecycleManager._interest_fingerprint([])
        )
        knowledge.apply_topic_lifecycle_assessment(other_plan)
        other_document = knowledge.load_topic_document("other_topic")
        other_document["lifecycle"]["refresh"]["due_at"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        knowledge._save(knowledge._topic_path("other_topic"), other_document)
        other_before = knowledge.load_topic_document("other_topic")

        calls = []

        def model(prompt, payload, **_kwargs):
            calls.append(prompt)
            if prompt == "prompts/nerv_topic_lifecycle.txt":
                return self._assessment(json.loads(payload)["topic"])
            self.fail("An unrelated Topic attempted to seed Curiosity")

        journal = CuriosityJournal(
            model,
            unload_model=lambda _name: None,
            base_dir=self.project,
        )
        manager = TopicLifecycleManager(model, curiosity_journal=journal)
        interest_reads = []

        def interest_signals(topic_id):
            interest_reads.append(topic_id)
            return []

        manager._interest_signals = interest_signals
        result = manager.run_once(
            preferred_topic_ids=[allowed["topic_id"]],
            only_topic_ids=[allowed["topic_id"]],
        )

        self.assertEqual(result["selected_topic_ids"], ["allowed_topic"])
        self.assertEqual(result["restricted_topic_ids"], ["allowed_topic"])
        self.assertEqual(result["curiosity_seed"]["reason"], "no_topic_seed_due")
        self.assertEqual(calls, ["prompts/nerv_topic_lifecycle.txt"])
        self.assertEqual(set(interest_reads), {"allowed_topic"})
        self.assertEqual(
            knowledge.load_topic_document("other_topic"),
            other_before,
        )

    def test_packet_is_bounded_without_dropping_claim_or_pending_ids(self):
        claims = [
            {
                "knowledge_id": "knowledge_" + str(index),
                "subject": "Large Topic",
                "claim": "x" * 2000,
                "facet": "background",
                "relationship_ids": [],
                "has_relationships": False,
                "knowledge_layer": "UNLAYERED",
                "fact_type": "UNCLASSIFIED",
                "knowledge_type": "stable",
                "expires_at": None,
                "temporal_scope": {},
            }
            for index in range(16)
        ]
        candidate = {
            "topic_id": "large_topic",
            "title": "Large Topic",
            "aliases": ["alias" + str(index) for index in range(30)],
            "keywords": ["keyword" + str(index) for index in range(50)],
            "claims": claims,
            "claim_count": 16,
            "context_complete": True,
            "layer_counts": {},
            "pending_layer_claim_ids": [
                value["knowledge_id"] for value in claims[:8]
            ],
            "pending_layer_total": 16,
            "pending_classification_claim_ids": [
                value["knowledge_id"] for value in claims[:8]
            ],
            "pending_classification_total": 16,
            "existing_classification": {},
            "classification_refinement_required": True,
            "classification_only_refinement": False,
            "assessment_fingerprint": "a" * 64,
            "existing_lifecycle": {},
            "updated_at": "",
        }
        packet = TopicLifecycleManager._fit_packet({
            "topic": TopicLifecycleManager._compact_candidate(candidate),
            "curiosity_interest_signals": [
                {"id": str(index), "question": "q" * 1000}
                for index in range(20)
            ],
            "existing_category_catalog": [
                {
                    "domain": "general",
                    "category_path": [
                        {"id": "category", "label": "category"},
                        {"id": "kind_" + str(index), "label": "k" * 120},
                    ],
                }
                for index in range(100)
            ],
        })

        self.assertLessEqual(
            TopicLifecycleManager._packet_bytes(packet),
            MAX_TOPIC_LIFECYCLE_INPUT_BYTES,
        )
        self.assertEqual(len(packet["topic"]["claims"]), 16)
        self.assertEqual(
            packet["topic"]["pending_layer_claim_ids"],
            candidate["pending_layer_claim_ids"],
        )

    def test_curator_restricts_lifecycle_to_topics_it_touched(self):
        item = self._item("knowledge_curated", "Curated Topic")
        knowledge._save_knowledge([item])
        lifecycle = Mock()
        lifecycle.due.return_value = False
        lifecycle.run_once.return_value = {
            "status": "COMPLETED",
            "assessed": 1,
            "failures": [],
        }

        def model(_prompt, payload, **_kwargs):
            packet = json.loads(payload)
            return {
                "curation_fingerprint": packet[
                    "required_curation_fingerprint"
                ],
                "assignments": [self._assignment(item, "curated_topic")],
                "reason": "Store one exact item.",
            }

        result = KnowledgeCurator(
            model, topic_lifecycle=lifecycle
        ).run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED")
        lifecycle.run_once.assert_called_once_with(
            preferred_topic_ids=["curated_topic"],
            only_topic_ids=["curated_topic"],
        )

    def test_generic_read_only_audit_accepts_current_and_legacy_contracts(self):
        candidate = self._create_topic(
            "topic_audit",
            self._item("knowledge_audit", "Topic Audit"),
        )
        plan = self._assessment(candidate)
        plan["_interest_fingerprint"] = (
            TopicLifecycleManager._interest_fingerprint([])
        )
        knowledge.apply_topic_lifecycle_assessment(plan)
        document = knowledge.load_topic_document("topic_audit")
        audit = knowledge.audit_topic_lifecycle_payloads(
            knowledge.load_items(), {"topic_audit": document}
        )
        self.assertTrue(audit["valid"], audit["failures"])
        self.assertEqual(audit["counts"]["contract_current"], 1)

        legacy = deepcopy(document)
        legacy["lifecycle"].pop("assessment_contract_version", None)
        legacy["semantic_contract"].pop(
            "topic_lifecycle_assessment_contract_version", None
        )
        legacy_audit = knowledge.audit_topic_lifecycle_payloads(
            knowledge.load_items(), {"topic_audit": legacy}
        )
        self.assertTrue(legacy_audit["valid"], legacy_audit["failures"])
        self.assertEqual(legacy_audit["counts"]["legacy_compatible"], 1)

        corrupted = deepcopy(document)
        corrupted["lifecycle"]["assessment_fingerprint"] = "0" * 64
        corrupted["lifecycle"]["assessment_contract_version"] = "broken"
        corrupted_audit = knowledge.audit_topic_lifecycle_payloads(
            knowledge.load_items(), {"topic_audit": corrupted}
        )
        self.assertFalse(corrupted_audit["valid"])
        self.assertIn(
            "topic_audit:assessment_fingerprint_mismatch",
            corrupted_audit["failures"],
        )
        self.assertIn(
            "topic_audit:assessment_contract_version_unknown",
            corrupted_audit["failures"],
        )

    def test_build_wiring_mirrors_and_companion_guard_are_preserved(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Legacy Visual Evidence Backfill V1.10.54.8",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(TOPIC_LIFECYCLE_ISOLATION_CONTRACT_VERSION, 1)
        self.assertEqual(
            knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION, 1
        )
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "knowledge_worker.py").read_bytes(),
            (ROOT / "casper" / "knowledge_worker.py").read_bytes(),
        )
        worker = (ROOT / "knowledge_worker.py").read_text(encoding="utf-8")
        self.assertIn("topic_lifecycle_isolation_contract_version", worker)
        validator = (
            ROOT / "TEST_TOPIC_LIFECYCLE_ISOLATION_V1_10_54_4.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("mode=ro", validator)
        self.assertIn("audit_topic_lifecycle_payloads", validator)
        self.assertIn("lifecycle_failures", validator)
        self.assertNotIn("live_akb_ids", validator)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("_companion_watch_owns_idle_time()", main)
        self.assertIn(BUILD_ID, main)


if __name__ == "__main__":
    unittest.main()
