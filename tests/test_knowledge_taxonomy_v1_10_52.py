import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
from nerv.topic_lifecycle import TopicLifecycleManager


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class KnowledgeTaxonomyV11052Tests(unittest.TestCase):
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

    @staticmethod
    def _item(item_id, subject, claim):
        return {
            "id": item_id,
            "subject": subject,
            "claim": claim,
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
            "provenance": {"origin": "nerv_curiosity"},
        }

    @staticmethod
    def _assignment(item, relationship=False):
        related = []
        if relationship:
            related = [{
                "id": "member_mumu",
                "name": "沐霂",
                "type": "member",
                "aliases": [],
                "relation": "member_of",
                "relation_direction": "RELATED_TO_SUBJECT",
                "claim_relation_evidence": "沐霂是四禧丸子成员",
            }]
        return {
            "knowledge_id": item["id"],
            "decision": "STORE",
            "topic_id": "sihixian_ecosystem",
            "topic_title": "四禧丸子",
            "topic_aliases": [],
            "topic_keywords": ["四禧丸子"],
            "subject_entity": {
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "group",
                "aliases": [],
            },
            "literal_claim_subject": "四禧丸子",
            "selected_subject_entity_id": "sihixian_maruko",
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "命题直接以四禧丸子为主语。",
            "related_entities": related,
            "facet": "membership" if relationship else "group_identity",
            "claim_keywords": ["四禧丸子"],
            "preferred_display_claim": item["claim"],
            "preferred_display_language": "zh-Hans",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "归入同一虚拟偶像生态主题。",
        }

    def _create_topic(self, relationship=False):
        claim = (
            "沐霂是四禧丸子成员。"
            if relationship
            else "四禧丸子是一个虚拟偶像团体。"
        )
        item = self._item("knowledge_taxonomy", "四禧丸子", claim)
        knowledge._save_knowledge([item])
        result = knowledge.apply_curator_assignments([
            self._assignment(item, relationship=relationship)
        ])
        self.assertEqual(result["curated"], 1)
        return item

    @staticmethod
    def _assessment(candidate, label="虚拟偶像"):
        claim_by_id = {
            value["knowledge_id"]: value
            for value in candidate["claims"]
        }
        all_ids = list(claim_by_id)
        return {
            "assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "assessment_fingerprint": candidate["assessment_fingerprint"],
            "topic_id": candidate["topic_id"],
            "claim_layers": [
                {
                    "knowledge_id": knowledge_id,
                    "knowledge_layer": (
                        "L3_RELATIONSHIPS"
                        if claim_by_id[knowledge_id]["has_relationships"]
                        else "L1_FOUNDATION"
                    ),
                    "reason": "按命题表达的知识深度归层。",
                }
                for knowledge_id in candidate["pending_layer_claim_ids"]
            ],
            "topic_classification": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domain": "culture_entertainment",
                "category_path": [
                    {"id": "idol_culture", "label": "偶像文化"},
                    {"id": "virtual_idols", "label": label},
                ],
                "reason": "主题聚合虚拟偶像团体的公共知识。",
            },
            "claim_classifications": [
                {
                    "knowledge_id": knowledge_id,
                    "fact_type": (
                        "RELATIONSHIP"
                        if claim_by_id[knowledge_id]["has_relationships"]
                        else "IDENTITY_DEFINITION"
                    ),
                    "reason": "按命题本身的事实形态归类。",
                }
                for knowledge_id in candidate[
                    "pending_classification_claim_ids"
                ]
            ],
            "target_layer": (
                "L3_RELATIONSHIPS"
                if any(value["has_relationships"] for value in claim_by_id.values())
                else "L1_FOUNDATION"
            ),
            "coverage": [
                {
                    "layer": layer,
                    "status": (
                        "COVERED"
                        if (
                            layer == "L3_RELATIONSHIPS"
                            and any(
                                value["has_relationships"]
                                for value in claim_by_id.values()
                            )
                        ) or (
                            layer == "L1_FOUNDATION"
                            and not any(
                                value["has_relationships"]
                                for value in claim_by_id.values()
                            )
                        )
                        else "NOT_NEEDED"
                    ),
                    "required_for_current_goal": (
                        layer == (
                            "L3_RELATIONSHIPS"
                            if any(
                                value["has_relationships"]
                                for value in claim_by_id.values()
                            )
                            else "L1_FOUNDATION"
                        )
                    ),
                    "evidence_claim_ids": (
                        all_ids
                        if layer == (
                            "L3_RELATIONSHIPS"
                            if any(
                                value["has_relationships"]
                                for value in claim_by_id.values()
                            )
                            else "L1_FOUNDATION"
                        )
                        else []
                    ),
                    "reason": "当前目标只需要已验证的对应层知识。",
                }
                for layer in knowledge.KNOWLEDGE_LAYERS
            ],
            "completion_score": 0.9,
            "confidence": 0.94,
            "state": "PAUSED_COMPLETE",
            "next_focus": "",
            "pause_reason": "当前目标已经覆盖。",
            "interest_score": 0.7,
            "interest_basis": "用户正在整理这个主题。",
            "refresh_after_days": 90,
            "reason": "分类与当前覆盖状态均有充分依据。",
        }

    def test_build_and_contract_versions_are_current(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(knowledge.KNOWLEDGE_TOPIC_SCHEMA_VERSION, 3)
        self.assertEqual(knowledge.KNOWLEDGE_CLASSIFICATION_VERSION, 1)
        self.assertEqual(
            knowledge.KNOWLEDGE_TAXONOMY_ACTIVE_CLAIM_INDEX_VERSION,
            1,
        )
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))

    def test_unclassified_legacy_topic_is_due(self):
        self._create_topic()
        candidates = knowledge.load_topic_lifecycle_assessment_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["existing_classification"], {})
        self.assertEqual(
            candidates[0]["pending_classification_claim_ids"],
            ["knowledge_taxonomy"],
        )

    def test_manager_classifies_topic_claim_and_builds_browse_index(self):
        self._create_topic()

        def model(prompt_path, payload, **_kwargs):
            self.assertEqual(prompt_path, "prompts/nerv_topic_lifecycle.txt")
            packet = json.loads(payload)
            self.assertEqual(packet["classification_contract"]["version"], 1)
            return self._assessment(packet["topic"])

        result = TopicLifecycleManager(model).run_once()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["classified"], 1)
        document = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(document["schema_version"], 3)
        self.assertEqual(
            document["classification"]["domain"],
            "culture_entertainment",
        )
        self.assertEqual(
            document["claims"][0]["curation"]["fact_type"],
            "IDENTITY_DEFINITION",
        )
        catalog = knowledge.load_category_catalog()
        self.assertEqual(catalog[0]["topic_ids"], ["sihixian_ecosystem"])
        browsed = knowledge.load_knowledge_by_category(
            domain="culture_entertainment",
            category_id="idol_culture",
            subcategory_id="virtual_idols",
            fact_type="IDENTITY_DEFINITION",
        )
        self.assertEqual([value["id"] for value in browsed], ["knowledge_taxonomy"])

    def test_relationship_claim_requires_relationship_fact_type(self):
        self._create_topic(relationship=True)
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        plan = self._assessment(candidate)
        plan["claim_classifications"][0]["fact_type"] = "HISTORY"
        normalized, errors = TopicLifecycleManager._validate_plan(
            plan,
            candidate,
        )
        self.assertIsNone(normalized)
        self.assertIn("relationship_fact_type_invalid", errors)

    def test_existing_category_id_cannot_silently_change_label(self):
        self._create_topic()
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        first = self._assessment(candidate)
        knowledge.apply_topic_lifecycle_assessment(first)
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            force_topic_ids=["sihixian_ecosystem"]
        )[0]
        changed = self._assessment(candidate, label="网络主播")
        normalized, errors = TopicLifecycleManager._validate_plan(
            changed,
            candidate,
            category_catalog=knowledge.load_category_catalog(),
        )
        self.assertIsNone(normalized)
        self.assertIn("category_label_mismatch", errors)

    def test_index_ignores_non_authoritative_topic_claim_copy(self):
        self._create_topic()
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        knowledge.apply_topic_lifecycle_assessment(
            self._assessment(candidate)
        )

        items = knowledge.load_items()
        items[0]["curation"]["status"] = "duplicate"
        knowledge._save_knowledge(items, sync_curation=False)
        legacy_index = knowledge.load_topic_index()
        legacy_index.pop("active_claim_index_version", None)
        knowledge._save(knowledge._topic_index_file(), legacy_index)

        knowledge.initialize()
        index = knowledge.load_topic_index()

        topic = index["topics"]["sihixian_ecosystem"]
        self.assertEqual(index["active_claim_index_version"], 1)
        self.assertEqual(topic["claim_count"], 0)
        self.assertEqual(topic["layer_counts"]["L1_FOUNDATION"], 0)
        self.assertEqual(topic["fact_type_counts"]["IDENTITY_DEFINITION"], 0)
        self.assertEqual(index["fact_type_counts"]["IDENTITY_DEFINITION"], 0)
        self.assertEqual(knowledge.load_knowledge_by_category(), [])
        topic_copy = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(topic_copy["claims"][0]["status"], "verified")

        validator = (ROOT / "TEST_KNOWLEDGE_TAXONOMY_V1_10_52.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("authoritative_active_ids", validator)

    def test_reclassification_keeps_a_bounded_audit_history(self):
        item = self._create_topic()
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        first = self._assessment(candidate)
        knowledge.apply_topic_lifecycle_assessment(first)
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            force_topic_ids=["sihixian_ecosystem"]
        )[0]
        second = self._assessment(candidate)
        second["topic_classification"]["category_path"] = [
            {"id": "performing_arts", "label": "表演艺术"},
            {"id": "stage_idols", "label": "舞台偶像"},
        ]
        knowledge.apply_topic_lifecycle_assessment(
            second,
            allow_reclassification=True,
        )
        document = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(len(document["classification_history"]), 1)
        self.assertEqual(
            document["classification_history"][0]["category_path"][1]["id"],
            "virtual_idols",
        )
        self.assertEqual(document["claims"][0]["claim"], item["claim"])
        self.assertEqual(
            knowledge.load_items()[0]["curation"]["classification_version"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
