import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class KnowledgeRelationshipTemporalScopeV110517Tests(unittest.TestCase):
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
            PENDING_SOURCES_FILE=str(root / "knowledge_source_candidates.json"),
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
            "cluster_label": "四禧丸子",
            "learned_at": now.isoformat(),
            "confidence": 1.0,
            "risk": "low",
            "status": "verified",
            "verification_status": "AI_PARTITIONED_AUDITED_FACT_LOOKUP",
            "verification": {
                "accepted_answer": claim + " 沐霂是四禧丸子成员。",
            },
            "sources": [{
                "title": "四禧丸子官方视频",
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
                "valid_for_days": 90,
                "expires_at": (now + timedelta(days=90)).isoformat(),
                "temporal_scope": {
                    "scope_type": "CURRENT_ACTIVE_STATE",
                    "requested_period": "current",
                    "allow_previous_period": False,
                    "closed_period": False,
                },
            })
        return item

    @staticmethod
    def _assignment(knowledge_id):
        return {
            "knowledge_id": knowledge_id,
            "decision": "STORE",
            "topic_id": "sihixian_ecosystem",
            "topic_title": "四禧丸子",
            "topic_aliases": ["四禧丸子"],
            "topic_keywords": ["四禧丸子", "虚拟偶像"],
            "subject_entity": {
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "group",
                "aliases": ["四禧丸子"],
            },
            "literal_claim_subject": "四禧丸子",
            "selected_subject_entity_id": "sihixian_maruko",
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "成员关系的明确团体主体。",
            "related_entities": [{
                "id": "member_mumu",
                "name": "沐霂",
                "type": "member",
                "aliases": [],
                "relation": "member_of",
                "relation_direction": "RELATED_TO_SUBJECT",
                "claim_relation_evidence": "沐霂是四禧丸子成员",
            }],
            "facet": "member_list",
            "claim_keywords": ["沐霂", "四禧丸子"],
            "preferred_display_claim": "沐霂是四禧丸子成员。",
            "preferred_display_language": "zh-CN",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "保存有来源约束的成员关系。",
        }

    def _curate_mixed_edge(self):
        current = self._item(
            "knowledge_current_roster",
            "四禧丸子当前官方成员名单包括沐霂。",
        )
        historical = self._item(
            "knowledge_2022_roster",
            "在2022年1月15日的官方资料中，成员名单包括沐霂。",
            historical=True,
        )
        knowledge._save_knowledge([current, historical])
        result = knowledge.apply_curator_assignments([
            self._assignment(current["id"]),
            self._assignment(historical["id"]),
        ])
        self.assertEqual(result["curated"], 2)
        return current, historical

    def test_build_contract_and_runtime_mirror_are_current(self):
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
        self.assertIn(
            'BEKKI_BUILD_ID = "' + BUILD_ID + '"',
            (ROOT / "main.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            knowledge.KNOWLEDGE_RELATIONSHIP_CONTRACT_VERSION,
            2,
        )
        self.assertEqual(
            knowledge.KNOWLEDGE_RELATIONSHIP_SUPPORT_MIGRATION_VERSION,
            1,
        )
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )

    def test_mixed_edge_exposes_disjoint_current_and_historical_views(self):
        current, historical = self._curate_mixed_edge()

        current_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem"
        )
        historical_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="historical",
        )
        all_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="all",
        )

        self.assertEqual(len(current_view), 1)
        self.assertEqual(len(historical_view), 1)
        self.assertEqual(len(all_view), 1)
        self.assertEqual(
            current_view[0]["active_supporting_knowledge_ids"],
            [current["id"]],
        )
        self.assertEqual(
            historical_view[0]["active_supporting_knowledge_ids"],
            [historical["id"]],
        )
        self.assertEqual(
            all_view[0]["active_supporting_knowledge_ids"],
            [current["id"], historical["id"]],
        )
        self.assertEqual(
            all_view[0]["temporal_status"],
            "CURRENT_AND_HISTORICAL",
        )
        self.assertTrue(all_view[0]["current_active"])
        self.assertTrue(all_view[0]["historical_active"])
        self.assertEqual(
            [value["knowledge_id"] for value in current_view[0]["evidence"]],
            [current["id"]],
        )
        self.assertEqual(
            [value["knowledge_id"] for value in historical_view[0]["evidence"]],
            [historical["id"]],
        )

    def test_fixed_history_cannot_keep_default_current_view_active(self):
        current, historical = self._curate_mixed_edge()
        items = knowledge.load_items()
        for item in items:
            if item.get("id") == current["id"]:
                item["expires_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat()
        knowledge._save_knowledge(items, sync_curation=False)

        self.assertEqual(
            knowledge.load_topic_relationships("sihixian_ecosystem"),
            [],
        )
        historical_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="historical",
        )
        all_view = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            temporal_view="all",
        )
        self.assertEqual(len(historical_view), 1)
        self.assertEqual(len(all_view), 1)
        self.assertFalse(all_view[0]["current_active"])
        self.assertTrue(all_view[0]["historical_active"])
        self.assertEqual(all_view[0]["temporal_status"], "HISTORICAL_ONLY")
        self.assertEqual(
            all_view[0]["active_supporting_knowledge_ids"],
            [historical["id"]],
        )
        inactive_current = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            active_only=False,
        )
        self.assertEqual(len(inactive_current), 1)
        self.assertFalse(inactive_current[0]["active"])
        self.assertTrue(inactive_current[0]["historical_active"])
        catalog = knowledge.load_topic_catalog(
            include_claims=True,
            max_topics=10,
            max_claims=10,
        )
        relationship = catalog[0]["relationships"][0]
        self.assertFalse(relationship["current_active"])
        self.assertTrue(relationship["historical_active"])
        self.assertEqual(
            relationship["historical_active_supporting_knowledge_ids"],
            [historical["id"]],
        )

    def test_relationship_contract_v1_migrates_without_changing_edge_id(self):
        current, historical = self._curate_mixed_edge()
        path = Path(knowledge._topic_path("sihixian_ecosystem"))
        document = json.loads(path.read_text(encoding="utf-8"))
        relationship_id = document["relationships"][0]["id"]
        document["semantic_contract"]["relationship_contract_version"] = 1
        document["relationships"][0]["contract_version"] = 1
        knowledge._save(str(path), document, backup=True)

        knowledge.initialize()
        migrated = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(
            migrated["semantic_contract"]["relationship_contract_version"],
            2,
        )
        self.assertEqual(
            migrated["semantic_contract"][
                "relationship_support_migration_version"
            ],
            1,
        )
        self.assertEqual(
            migrated["relationships"][0]["contract_version"],
            2,
        )
        self.assertEqual(migrated["relationships"][0]["id"], relationship_id)
        self.assertEqual(
            migrated["relationships"][0]["supporting_knowledge_ids"],
            [current["id"], historical["id"]],
        )

    def test_invalid_temporal_view_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "invalid_relationship_temporal_view",
        ):
            knowledge.load_topic_relationships(temporal_view="presentish")


if __name__ == "__main__":
    unittest.main()
