import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class KnowledgeRelationshipSupportRecoveryV110518Tests(unittest.TestCase):
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
    def _item(knowledge_id, claim, *, historical=False):
        now = datetime.now(timezone.utc)
        item = {
            "id": knowledge_id,
            "subject": "四禧丸子",
            "claim": claim,
            "topics": ["四禧丸子", "成员名单"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "member_list",
            "learned_at": now.isoformat(),
            "confidence": 1.0,
            "risk": "low",
            "status": "verified",
            "verification_status": "AI_PARTITIONED_AUDITED_FACT_LOOKUP",
            "verification": {"accepted_answer": claim},
            "sources": [{
                "title": "四禧丸子官方资料",
                "url": "https://www.bilibili.com/video/BV1example",
                "domain": "bilibili.com",
            }],
        }
        if historical:
            item.update({
                "knowledge_type": "stable",
                "valid_for_days": None,
                "expires_at": None,
                "temporal_scope": {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": "2022-01-15",
                    "allow_previous_period": False,
                    "closed_period": True,
                },
            })
        else:
            item.update({
                "knowledge_type": "reviewable",
                "valid_for_days": 365,
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "temporal_scope": None,
            })
        return item

    @staticmethod
    def _assignment(knowledge_id, evidence_text):
        members = (
            ("member_3fa5129a59fb8e22", "沐霂"),
            ("member_2f1049a500b736c3", "又一"),
            ("member_683fc423d6cc60f9", "梨安"),
            ("member_35409d8c22e35dd6", "恬豆"),
        )
        return {
            "knowledge_id": knowledge_id,
            "decision": "STORE",
            "topic_id": "sihixian_ecosystem",
            "topic_title": "四禧丸子",
            "topic_aliases": ["四禧丸子"],
            "topic_keywords": ["四禧丸子"],
            "subject_entity": {
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "group",
                "aliases": ["四禧丸子"],
            },
            "literal_claim_subject": "四禧丸子",
            "selected_subject_entity_id": "sihixian_maruko",
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "名单所属团体。",
            "related_entities": [
                {
                    "id": entity_id,
                    "name": name,
                    "type": "member",
                    "aliases": [],
                    "relation": "member_of",
                    "relation_direction": "RELATED_TO_SUBJECT",
                    "claim_relation_evidence": evidence_text,
                }
                for entity_id, name in members
            ],
            "facet": "historical_roster" if "2022" in evidence_text else "member_list",
            "claim_keywords": ["成员名单"],
            "preferred_display_claim": evidence_text,
            "preferred_display_language": "zh-CN",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "保存四条成员到团体的关系。",
        }

    def _curate_current_and_history(self):
        current = self._item(
            "knowledge_cb0560f25bc7f9f9",
            "官方公开的成员名单为：沐霂、又一、梨安、恬豆。",
        )
        historical = self._item(
            "knowledge_7f34f865adb6fd58",
            "在2022年1月15日的官方视频中，四禧丸子公开资料列出的四位成员为沐霂、恬豆、梨安、又一。",
            historical=True,
        )
        knowledge._save_knowledge([current, historical])
        current_evidence = "成员名单为：沐霂、又一、梨安、恬豆"
        historical_evidence = "四位成员为沐霂、恬豆、梨安、又一"
        result = knowledge.apply_curator_assignments([
            self._assignment(current["id"], current_evidence),
            self._assignment(historical["id"], historical_evidence),
        ])
        self.assertEqual(result["curated"], 2)
        return current, historical

    def test_build_contract_is_current(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Autonomous Visual Evidence V1.10.54.6",
        )
        self.assertEqual(
            knowledge.KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION,
            1,
        )

    def test_distinct_per_claim_evidence_survives_contract_rebuild(self):
        current, historical = self._curate_current_and_history()
        path = knowledge._topic_path("sihixian_ecosystem")
        document = knowledge._load(path, None)
        document["semantic_contract"].pop(
            "relationship_support_migration_version",
            None,
        )
        knowledge._save(path, document, backup=True)

        knowledge.initialize()

        migrated = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(
            migrated["semantic_contract"][
                "relationship_support_migration_version"
            ],
            1,
        )
        self.assertEqual(len(migrated["relationships"]), 4)
        for relationship in migrated["relationships"]:
            self.assertEqual(
                relationship["supporting_knowledge_ids"],
                [current["id"], historical["id"]],
            )
            evidence = {
                value["knowledge_id"]: value["text"]
                for value in relationship["evidence"]
            }
            self.assertIn("成员名单为", evidence[current["id"]])
            self.assertNotIn("2022年1月15日", evidence[current["id"]])
            self.assertIn("四位成员为", evidence[historical["id"]])

    def test_v1_10_51_7_dropped_support_recovers_from_ledger(self):
        current, historical = self._curate_current_and_history()
        path = knowledge._topic_path("sihixian_ecosystem")
        document = knowledge._load(path, None)
        original_edge_ids = {
            value["id"] for value in document["relationships"]
        }
        for claim in document["claims"]:
            if claim.get("id") == current["id"]:
                claim["curation"]["relationship_ids"] = []
        for relationship in document["relationships"]:
            relationship["supporting_knowledge_ids"] = [historical["id"]]
            relationship["evidence"] = [
                value for value in relationship["evidence"]
                if value.get("knowledge_id") == historical["id"]
            ]
            relationship["claim_relation_evidence"] = (
                "四位成员为沐霂、恬豆、梨安、又一"
            )
            relationship["contract_version"] = 2
        document["semantic_contract"]["relationship_contract_version"] = 2
        document["semantic_contract"].pop(
            "relationship_support_migration_version",
            None,
        )
        knowledge._save(path, document, backup=True)

        knowledge.initialize()

        repaired = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(
            {value["id"] for value in repaired["relationships"]},
            original_edge_ids,
        )
        self.assertEqual(len(repaired["relationships"]), 4)
        for relationship in repaired["relationships"]:
            self.assertEqual(
                relationship["supporting_knowledge_ids"],
                [historical["id"], current["id"]],
            )
        current_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
        )
        historical_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="historical",
        )
        all_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="all",
        )
        self.assertEqual(len(current_view), 4)
        self.assertEqual(len(historical_view), 4)
        self.assertEqual(len(all_view), 4)
        self.assertTrue(all(
            value["temporal_status"] == "CURRENT_AND_HISTORICAL"
            for value in all_view
        ))
        self.assertTrue(all(
            value["active_supporting_knowledge_ids"] == [current["id"]]
            for value in current_view
        ))
        self.assertTrue(all(
            value["active_supporting_knowledge_ids"] == [historical["id"]]
            for value in historical_view
        ))

    def test_claim_text_mismatch_cannot_hydrate_ledger_relationship_ids(self):
        current, historical = self._curate_current_and_history()
        path = knowledge._topic_path("sihixian_ecosystem")
        document = knowledge._load(path, None)
        for claim in document["claims"]:
            if claim.get("id") == current["id"]:
                claim["claim"] = "不相干的主题副本。"
                claim["curation"]["relationship_ids"] = []
        for relationship in document["relationships"]:
            relationship["supporting_knowledge_ids"] = [historical["id"]]
            relationship["evidence"] = [
                value for value in relationship["evidence"]
                if value.get("knowledge_id") == historical["id"]
            ]
        document["semantic_contract"].pop(
            "relationship_support_migration_version",
            None,
        )
        knowledge._save(path, document, backup=True)

        knowledge.initialize()

        repaired = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertTrue(all(
            current["id"] not in value["supporting_knowledge_ids"]
            for value in repaired["relationships"]
        ))


if __name__ == "__main__":
    unittest.main()
