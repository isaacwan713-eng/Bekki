import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


def make_item(item_id, subject, claim):
    return {
        "id": item_id,
        "subject": subject,
        "claim": claim,
        "topics": [subject],
        "knowledge_domain": "general",
        "cluster_label": subject,
        "learned_at": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.95,
        "knowledge_type": "stable",
        "valid_for_days": None,
        "expires_at": None,
        "risk": "low",
        "status": "verified",
        "verification_status": "AI_PLUS_SOURCE_CORROBORATION",
        "sources": [],
        "provenance": {"origin": "terminal_outcome_test"},
    }


def assignment(item, decision="STORE", related_claim_ids=None):
    topic_id = "manchester_united_ecosystem"
    return {
        "knowledge_id": item["id"],
        "decision": decision,
        "topic_id": topic_id,
        "topic_title": "Manchester United",
        "topic_aliases": ["Manchester United"],
        "topic_keywords": ["Manchester United"],
        "subject_entity": {
            "id": "manchester_united",
            "name": "Manchester United",
            "type": "football_club",
            "aliases": [],
        },
        "literal_claim_subject": item["subject"],
        "selected_subject_entity_id": "manchester_united",
        "rejected_adjacent_entity_ids": [],
        "subject_selection_reason": "The exact club is the claim subject.",
        "related_entities": [],
        "facet": "club_identity",
        "claim_keywords": ["Manchester United"],
        "preferred_display_claim": item["claim"],
        "preferred_display_language": "source",
        "name_rendering_status": "SOURCE_PRESERVED",
        "display_semantics_preserved": True,
        "related_claim_ids": list(related_claim_ids or []),
        "entity_scope_preserved": True,
        "relationship_semantics_consistent": True,
        "reason": "Terminal outcome test assignment.",
    }


class CuratorTerminalOutcomeTests(unittest.TestCase):
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
            PENDING_SOURCES_FILE=str(
                data / "knowledge_source_candidates.json"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    @staticmethod
    def _payloads():
        topics = {}
        for document in knowledge._topic_documents():
            topic = document.get("topic", {})
            topics[str(topic.get("id") or "")] = document
        return {
            "ledger": knowledge.load_items(),
            "inbox": knowledge._load(
                knowledge._curation_inbox_file(), {"items": []}
            ),
            "topic_documents": topics,
            "conflicts": knowledge._load(
                knowledge._conflicts_file(), {"items": []}
            ),
        }

    def _store_seed(self):
        seed = make_item(
            "knowledge_manchester_identity",
            "Manchester United",
            "Manchester United is an English football club.",
        )
        knowledge._save_knowledge([seed])
        counts = knowledge.apply_curator_assignments([assignment(seed)])
        self.assertEqual(counts["curated"], 1)
        return knowledge.load_items()[0]

    def _add_item(self, value):
        stored = knowledge.load_items()
        stored.append(value)
        knowledge._save_knowledge(stored)

    def test_curated_outcome_closes_through_exact_topic_claim(self):
        self._store_seed()
        result = knowledge.audit_curator_terminal_outcome_payloads(
            **self._payloads()
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["counts"]["curated"], 1)
        self.assertEqual(
            result["outcomes"][0]["resolved_topic_ids"],
            ["manchester_united_ecosystem"],
        )

    def test_duplicate_outcome_must_resolve_to_real_topic_claim(self):
        seed = self._store_seed()
        duplicate = make_item(
            "knowledge_manchester_duplicate",
            "Manchester United",
            "Manchester United is a football club in England.",
        )
        self._add_item(duplicate)
        counts = knowledge.apply_curator_assignments([
            assignment(
                duplicate,
                decision="DUPLICATE",
                related_claim_ids=[seed["id"]],
            )
        ])
        self.assertEqual(counts["duplicate"], 1)

        payloads = self._payloads()
        result = knowledge.audit_curator_terminal_outcome_payloads(**payloads)
        self.assertTrue(result["valid"])
        self.assertEqual(result["counts"]["duplicate"], 1)

        broken = deepcopy(payloads)
        for value in broken["ledger"]:
            if value.get("id") == duplicate["id"]:
                value["curation"]["duplicate_of"] = "knowledge_missing"
        result = knowledge.audit_curator_terminal_outcome_payloads(**broken)
        self.assertFalse(result["valid"])
        self.assertIn(
            duplicate["id"] + ":duplicate_target_not_in_topic",
            result["failures"],
        )

    def test_conflict_outcome_closes_through_topic_and_related_claim(self):
        seed = self._store_seed()
        current = make_item(
            "knowledge_manchester_conflict",
            "Manchester United",
            "Manchester United is not an English football club.",
        )
        self._add_item(current)
        counts = knowledge.apply_curator_assignments([
            assignment(
                current,
                decision="CONFLICT",
                related_claim_ids=[seed["id"]],
            )
        ])
        self.assertEqual(counts["conflict"], 1)

        payloads = self._payloads()
        result = knowledge.audit_curator_terminal_outcome_payloads(**payloads)
        self.assertTrue(result["valid"])
        self.assertEqual(result["counts"]["conflict"], 1)

        broken = deepcopy(payloads)
        broken["conflicts"]["items"][0]["related_claim_ids"] = [
            "knowledge_missing"
        ]
        result = knowledge.audit_curator_terminal_outcome_payloads(**broken)
        self.assertFalse(result["valid"])
        self.assertIn(
            current["id"]
            + ":conflict_target_not_in_topic:knowledge_missing",
            result["failures"],
        )

    def test_v54_3_conflict_without_inline_topic_metadata_is_supported(self):
        seed = self._store_seed()
        current = make_item(
            "knowledge_legacy_conflict",
            "Manchester United",
            "Manchester United is not an English football club.",
        )
        self._add_item(current)
        knowledge.apply_curator_assignments([
            assignment(
                current,
                decision="CONFLICT",
                related_claim_ids=[seed["id"]],
            )
        ])
        payloads = self._payloads()
        for value in payloads["ledger"]:
            if value.get("id") == current["id"]:
                value["curation"].pop("topic_id", None)
                value["curation"].pop("related_claim_ids", None)
                value["curation"].pop(
                    "terminal_outcome_contract_version", None
                )

        result = knowledge.audit_curator_terminal_outcome_payloads(**payloads)
        self.assertTrue(result["valid"])
        conflict = next(
            value for value in result["outcomes"]
            if value["knowledge_id"] == current["id"]
        )
        self.assertEqual(
            conflict["resolved_topic_ids"],
            ["manchester_united_ecosystem"],
        )

    def test_conflict_cannot_point_to_target_in_another_topic(self):
        seed = self._store_seed()
        current = make_item(
            "knowledge_cross_topic_conflict",
            "Manchester United",
            "Manchester United is not an English football club.",
        )
        self._add_item(current)
        knowledge.apply_curator_assignments([
            assignment(
                current,
                decision="CONFLICT",
                related_claim_ids=[seed["id"]],
            )
        ])
        payloads = self._payloads()
        payloads["topic_documents"]["unrelated_topic"] = {
            "topic": {"id": "unrelated_topic", "title": "Unrelated"},
            "entities": {},
            "claims": [],
        }
        payloads["conflicts"]["items"][0]["topic_id"] = "unrelated_topic"

        result = knowledge.audit_curator_terminal_outcome_payloads(**payloads)
        self.assertFalse(result["valid"])
        self.assertIn(
            current["id"]
            + ":conflict_target_not_in_topic:"
            + seed["id"],
            result["failures"],
        )


class CuratorTerminalOutcomeBuildTests(unittest.TestCase):
    def test_build_and_generic_validator_contract(self):
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
            knowledge.CURATOR_TERMINAL_OUTCOME_CONTRACT_VERSION, 1
        )
        validator = (
            ROOT
            / "TEST_KNOWLEDGE_CURATOR_TERMINAL_OUTCOMES_V1_10_54_3_1.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("audit_curator_terminal_outcome_payloads", validator)
        self.assertIn("terminal_outcome_failures", validator)
        self.assertNotIn("live_akb_ids", validator)
        self.assertNotIn("knowledge_75b2fc4fdc56dba8", validator)

    def test_mirrors_worker_diagnostic_and_release_notes(self):
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )
        self.assertEqual(
            (ROOT / "knowledge_worker.py").read_bytes(),
            (ROOT / "casper" / "knowledge_worker.py").read_bytes(),
        )
        worker = (ROOT / "knowledge_worker.py").read_text(encoding="utf-8")
        self.assertIn("curator_terminal_outcome_contract_version", worker)
        self.assertTrue((
            ROOT
            / "KNOWLEDGE_CURATOR_TERMINAL_OUTCOMES_V1_10_54_3_1_NOTES.md"
        ).is_file())


if __name__ == "__main__":
    unittest.main()
