import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
from nerv import external_fact_fallback
from nerv.knowledge_curator import KnowledgeCurator
from nerv.topic_lifecycle import TopicLifecycleManager


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class KnowledgeRelationshipGroundingV11051Tests(unittest.TestCase):
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
    def _roster_claim():
        return "四禧丸子官方成员名单为沐霂、又一、梨安、恬豆。"

    @classmethod
    def _roster_item(cls):
        now = datetime.now(timezone.utc)
        claim = cls._roster_claim()
        return {
            "id": "knowledge_sihixian_roster",
            "subject": "四禧丸子官方成员名单",
            "claim": claim,
            "topics": ["四禧丸子"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "四禧丸子",
            "learned_at": now.isoformat(),
            "confidence": 0.95,
            "knowledge_type": "reviewable",
            "valid_for_days": 180,
            "expires_at": (now + timedelta(days=180)).isoformat(),
            "risk": "low",
            "status": "verified",
            "verification_status": "AI_PLUS_SOURCE_CORROBORATION",
            "verification": {
                "original_request": "Sihixian 最初的四位成员分别是谁？",
                "accepted_answer": claim,
            },
            "sources": [{
                "title": "四禧丸子官方成员介绍",
                "url": "https://example.test/sihixian/official",
                "domain": "example.test",
            }],
            "provenance": {"origin": "casper_audited_fact_lookup"},
        }

    @classmethod
    def _roster_assignment(cls, names=None):
        names = names or ["沐霂", "又一", "梨安", "恬豆"]
        ids = {
            "沐霂": "mumu",
            "又一": "youyi",
            "梨安": "lian",
            "恬豆": "tiandou",
        }
        claim = cls._roster_claim()
        return {
            "knowledge_id": "knowledge_sihixian_roster",
            "decision": "STORE",
            "topic_id": "sihixian_ecosystem",
            "topic_title": "Sihixian (四禧丸子) Virtual Idol Group",
            "topic_aliases": ["四禧丸子", "Sihixian", "Sihixian Maruko"],
            "topic_keywords": ["四禧丸子", "Sihixian", "virtual idol"],
            "subject_entity": {
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "virtual_idol_group",
                "aliases": ["Sihixian"],
            },
            "literal_claim_subject": "四禧丸子",
            "selected_subject_entity_id": "sihixian_maruko",
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "四禧丸子是名单所属的明确主体。",
            "related_entities": [
                {
                    "id": ids[name],
                    "name": name,
                    "type": "person",
                    "aliases": ["Invented " + ids[name]],
                    "relation": "member_of",
                    "relation_direction": "RELATED_TO_SUBJECT",
                    "claim_relation_evidence": claim,
                }
                for name in names
            ],
            "facet": "official_member_roster",
            "claim_keywords": ["成员名单", "Sihixian"],
            "preferred_display_claim": claim,
            "preferred_display_language": "zh-CN",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "完整官方名单形成四条成员到团体的关系。",
        }

    @staticmethod
    def _isolated_model(plan):
        def run(_prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            value = deepcopy(plan)
            value["curation_fingerprint"] = packet[
                "required_curation_fingerprint"
            ]
            return value

        return Mock(side_effect=run)

    def _curate_roster(self):
        item = self._roster_item()
        knowledge._save_knowledge([item])
        plan = {
            "assignments": [self._roster_assignment()],
            "reason": "将完整名单保存在同一团体主题中。",
        }
        result = KnowledgeCurator(self._isolated_model(plan)).run_once(
            force=True
        )
        self.assertEqual(result["status"], "COMPLETED")
        return item

    @staticmethod
    def _lifecycle_plan(candidate, layer="L3_RELATIONSHIPS"):
        knowledge_id = candidate["pending_layer_claim_ids"][0]
        coverage = []
        for name in knowledge.KNOWLEDGE_LAYERS:
            covered = name == "L3_RELATIONSHIPS"
            coverage.append({
                "layer": name,
                "status": "COVERED" if covered else "NOT_NEEDED",
                "required_for_current_goal": covered,
                "evidence_claim_ids": [knowledge_id] if covered else [],
                "reason": "当前目标只需要已验证的成员关系。",
            })
        return {
            "assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "assessment_fingerprint": candidate["assessment_fingerprint"],
            "topic_id": candidate["topic_id"],
            "claim_layers": [{
                "knowledge_id": knowledge_id,
                "knowledge_layer": layer,
                "reason": "该命题直接表达成员与团体的关系。",
            }],
            "topic_classification": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domain": "culture_entertainment",
                "category_path": [
                    {"id": "idol_culture", "label": "偶像文化"},
                    {"id": "virtual_idols", "label": "虚拟偶像"},
                ],
                "reason": "该主题属于虚拟偶像团体知识。",
            },
            "claim_classifications": [{
                "knowledge_id": knowledge_id,
                "fact_type": "RELATIONSHIP",
                "reason": "该事实记录成员与团体之间的关系。",
            }],
            "target_layer": "L3_RELATIONSHIPS",
            "coverage": coverage,
            "completion_score": 0.9,
            "confidence": 0.94,
            "state": "PAUSED_COMPLETE",
            "next_focus": "",
            "pause_reason": "当前成员关系目标已有完整名单覆盖。",
            "interest_score": 0.8,
            "interest_basis": "用户明确要求为后续关系知识做准备。",
            "refresh_after_days": 30,
            "reason": "已覆盖当前关系目标，可等待复查。",
        }

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
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )
        lifecycle_prompt = (
            ROOT / "prompts" / "nerv_topic_lifecycle.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("has_relationships=true", lifecycle_prompt)
        self.assertIn("L3_RELATIONSHIPS", lifecycle_prompt)
        self.assertTrue(
            (
                ROOT
                / "TEST_KNOWLEDGE_RELATIONSHIP_HOTFIX_V1_10_51_1.ps1"
            ).is_file()
        )
        self.assertTrue(
            (
                ROOT
                / "KNOWLEDGE_RELATIONSHIP_LIVE_RECOVERY_HOTFIX_V1_10_51_1_NOTES.md"
            ).is_file()
        )

    def test_fixed_history_without_period_recovers_to_reviewable_roster(self):
        records = [{
            "audit_id": "partition_claim_0",
            "subject": "四禧丸子官方成员名单",
            "claim": self._roster_claim(),
            "proposed_persist": True,
            "persistence_eligible": True,
            "proposed_knowledge_type": "stable",
            "proposed_valid_for_days": None,
            "confidence": 0.95,
            "temporal_scope": {},
        }]
        invalid = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "FIXED_HISTORY",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "Incorrectly treated a current roster as history.",
            }],
            "reason": "First audit.",
        }
        recovered = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "reason": "A complete current official roster is reusable but mutable.",
            }],
            "reason": "Recovered current-roster lifecycle.",
        }
        with patch(
            "tools.run_ai_prompt",
            side_effect=[invalid, recovered],
        ) as model, patch("tools.unload_model"):
            decisions = external_fact_fallback._run_partition_lifecycle_audit(
                records,
                {"mode": "sihixian_roster_test"},
            )

        self.assertEqual(model.call_count, 1)
        self.assertTrue(decisions[0]["persist"])
        self.assertEqual(decisions[0]["knowledge_type"], "reviewable")
        self.assertEqual(decisions[0]["valid_for_days"], 365)

    def test_maintained_current_roster_cannot_remain_stable(self):
        records = [{
            "audit_id": "partition_claim_0",
            "subject": "四禧丸子",
            "claim": "官方公开的成员名单为：沐霂、又一、梨安、恬豆。",
            "proposed_persist": True,
            "persistence_eligible": True,
            "proposed_knowledge_type": "stable",
            "proposed_valid_for_days": None,
            "confidence": 1.0,
            "temporal_scope": None,
            "current_people_roster": True,
        }]
        invalid = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "Incorrectly treated the current roster as stable.",
            }],
            "reason": "First audit.",
        }
        recovered = {
            "decisions": [{
                "audit_id": "partition_claim_0",
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 90,
                "lifecycle_proportional": True,
                "reason": "A current people roster is reusable but mutable.",
            }],
            "reason": "Recovered current roster.",
        }

        with patch(
            "tools.run_ai_prompt",
            side_effect=[invalid, recovered],
        ) as model, patch("tools.unload_model"):
            decisions = external_fact_fallback._run_partition_lifecycle_audit(
                records,
                {"mode": "live_sihixian_roster_regression"},
            )

        self.assertEqual(model.call_count, 1)
        self.assertEqual(decisions[0]["knowledge_type"], "reviewable")
        self.assertEqual(decisions[0]["valid_for_days"], 365)

    def test_incomplete_member_relationships_are_rejected(self):
        item = self._roster_item()
        assignment = self._roster_assignment(["沐霂", "又一", "梨安"])
        assignments, errors = KnowledgeCurator._validate_plan(
            {"assignments": [assignment], "reason": "Incomplete."},
            [item["id"]],
            [],
            evidence_items={item["id"]: item},
        )

        self.assertIsNone(assignments)
        self.assertIn("membership_relationships_incomplete", errors)

    def test_two_ai_omissions_repair_literal_roster_and_commit_four_edges(self):
        item = self._roster_item()
        knowledge._save_knowledge([item])
        empty_assignment = self._roster_assignment()
        empty_assignment["related_entities"] = []
        incomplete_plan = {
            "assignments": [empty_assignment],
            "reason": "The model omitted explicit membership edges.",
        }
        model = self._isolated_model(incomplete_plan)

        result = KnowledgeCurator(model).run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(model.call_count, 2)
        relationships = knowledge.load_topic_relationships(
            "sihixian_ecosystem"
        )
        self.assertEqual(len(relationships), 4)
        self.assertEqual(
            {value["source_entity_name"] for value in relationships},
            {"沐霂", "又一", "梨安", "恬豆"},
        )
        self.assertEqual(
            {value["relation"] for value in relationships},
            {"member_of"},
        )
        self.assertTrue(all(
            value["active_supporting_knowledge_ids"] == [item["id"]]
            for value in relationships
        ))

    def test_literal_roster_repair_refuses_an_adjacent_subject(self):
        item = self._roster_item()
        assignment = self._roster_assignment()
        assignment["subject_entity"] = {
            "id": "snh48",
            "name": "SNH48",
            "type": "organization",
            "aliases": [],
        }
        assignment["selected_subject_entity_id"] = "snh48"
        assignment["literal_claim_subject"] = "SNH48"
        assignment["related_entities"] = []

        _repaired, repaired_ids = (
            KnowledgeCurator._repair_explicit_membership_relationships(
                {
                    "assignments": [assignment],
                    "reason": "Wrong adjacent subject.",
                },
                {item["id"]: item},
                [],
            )
        )

        self.assertEqual(repaired_ids, [])

    def test_roster_creates_four_grounded_member_to_group_edges(self):
        item = self._curate_roster()
        topic = knowledge.load_topic_document("sihixian_ecosystem")
        relationships = knowledge.load_topic_relationships(
            "sihixian_ecosystem"
        )

        self.assertEqual(topic["topic"]["title"], "四禧丸子")
        self.assertEqual(topic["topic"]["aliases"], ["四禧丸子"])
        self.assertNotIn("Sihixian", topic["topic"]["keywords"])
        self.assertEqual(
            topic["entities"]["sihixian_maruko"]["aliases"],
            [],
        )
        self.assertEqual(len(relationships), 4)
        self.assertEqual(
            {value["source_entity_name"] for value in relationships},
            {"沐霂", "又一", "梨安", "恬豆"},
        )
        self.assertEqual(
            {value["target_entity_id"] for value in relationships},
            {"sihixian_maruko"},
        )
        self.assertEqual(
            {value["relation"] for value in relationships},
            {"member_of"},
        )
        self.assertTrue(all(
            value["active_supporting_knowledge_ids"] == [item["id"]]
            for value in relationships
        ))
        curated_claim = topic["claims"][0]
        self.assertEqual(len(curated_claim["curation"]["relationship_ids"]), 4)
        self.assertNotIn("Sihixian", curated_claim["curation"]["keywords"])

    def test_adjacent_answer_context_cannot_create_unstated_snh_relation(self):
        item = self._roster_item()
        item["id"] = "knowledge_sihixian_setting"
        item["subject"] = "四禧丸子人设"
        item["claim"] = (
            "四禧丸子的背景故事围绕老字号点心店禧運楼，角色造型融入国风元素。"
        )
        item["verification"]["accepted_answer"] = (
            item["claim"] + " 四位成员可能与SNH48存在历史关联。"
        )
        assignment = self._roster_assignment([])
        assignment["knowledge_id"] = item["id"]
        assignment["related_entities"] = [{
            "id": "snh48",
            "name": "SNH48",
            "type": "organization",
            "aliases": [],
            "relation": "former_member_of",
            "relation_direction": "SUBJECT_TO_RELATED",
            "claim_relation_evidence": "可能与SNH48存在历史关联",
        }]
        assignments, errors = KnowledgeCurator._validate_plan(
            {"assignments": [assignment], "reason": "Adjacent context."},
            [item["id"]],
            [],
            evidence_items={item["id"]: item},
        )

        self.assertIsNone(assignments)
        self.assertIn("ungrounded_related_entity", errors)
        self.assertIn("ungrounded_claim_relation_evidence", errors)

    def test_legacy_reversed_pairing_edges_are_repaired_with_provenance(self):
        claim = {
            "id": "knowledge_ka_huang_pairing",
            "subject": "卡黄",
            "claim": "卡黄指代成员李艺彤与黄婷婷组成的组合。",
            "knowledge_type": "stable",
            "expires_at": None,
            "status": "verified",
            "curation": {
                "status": "curated",
                "topic_id": "ka_huang",
                "subject_entity_id": "ka_huang",
                "related_entity_ids": [
                    "li_yitong", "huang_tingting", "snh48"
                ],
                "knowledge_layer": "L2_CONTEXT",
                "knowledge_layer_version": knowledge.KNOWLEDGE_LAYER_VERSION,
                "knowledge_layer_reason": "Legacy misclassification.",
            },
        }
        knowledge._save_knowledge([claim])
        legacy = {
            "schema_version": 2,
            "topic": {
                "id": "ka_huang",
                "title": "Ka Huang pairing",
                "aliases": ["卡黄", "KaHuang"],
                "keywords": ["卡黄", "pairing"],
            },
            "entities": {
                "ka_huang": {
                    "id": "ka_huang",
                    "name": "卡黄",
                    "type": "pairing",
                    "aliases": ["KaHuang"],
                },
                "li_yitong": {
                    "id": "li_yitong",
                    "name": "李艺彤",
                    "type": "person",
                    "aliases": [],
                },
                "huang_tingting": {
                    "id": "huang_tingting",
                    "name": "黄婷婷",
                    "type": "person",
                    "aliases": [],
                },
                "snh48": {
                    "id": "snh48",
                    "name": "SNH48",
                    "type": "organization",
                    "aliases": [],
                },
            },
            "relationships": [
                {
                    "id": "relation_old_one",
                    "source_entity_id": "ka_huang",
                    "relation": "member_of_pairing",
                    "target_entity_id": "li_yitong",
                    "claim_relation_evidence": claim["claim"],
                },
                {
                    "id": "relation_old_unsupported",
                    "source_entity_id": "ka_huang",
                    "relation": "former_member_of",
                    "target_entity_id": "snh48",
                    "claim_relation_evidence": "卡黄曾属于SNH48。",
                },
                {
                    "id": "relation_old_two",
                    "source_entity_id": "ka_huang",
                    "relation": "member_of_pairing",
                    "target_entity_id": "huang_tingting",
                    "claim_relation_evidence": claim["claim"],
                },
            ],
            "claims": [deepcopy(claim)],
            "lifecycle": {},
        }
        knowledge._save(knowledge._topic_path("ka_huang"), legacy)

        repaired = knowledge.load_topic_document("ka_huang")
        relationships = knowledge.load_topic_relationships("ka_huang")

        self.assertEqual(repaired["topic"]["title"], "卡黄")
        self.assertEqual(repaired["topic"]["aliases"], ["卡黄"])
        self.assertEqual(
            {value["source_entity_id"] for value in relationships},
            {"li_yitong", "huang_tingting"},
        )
        self.assertEqual(
            {value["target_entity_id"] for value in relationships},
            {"ka_huang"},
        )
        self.assertTrue(all(
            value["supporting_knowledge_ids"] == [claim["id"]]
            for value in relationships
        ))
        self.assertEqual(
            repaired["semantic_contract"]["version"],
            knowledge.KNOWLEDGE_SEMANTIC_CONTRACT_VERSION,
        )
        self.assertEqual(
            repaired["relationship_quarantine"][-1]["quarantine_reason"],
            "legacy_relationship_not_grounded_in_claim",
        )
        self.assertNotIn(
            "knowledge_layer",
            repaired["claims"][0]["curation"],
        )
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            preferred_topic_ids=["ka_huang"],
            limit=1,
        )[0]
        self.assertEqual(
            candidate["pending_layer_claim_ids"],
            [claim["id"]],
        )

    def test_expired_authoritative_claim_hides_topic_copy_relationships(self):
        item = self._curate_roster()
        stored = knowledge.load_items()[0]
        stored["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        knowledge._save_knowledge([stored])

        self.assertEqual(
            knowledge.load_topic_relationships("sihixian_ecosystem"),
            [],
        )
        inactive = knowledge.load_topic_relationships(
            "sihixian_ecosystem",
            active_only=False,
        )
        self.assertEqual(len(inactive), 4)
        self.assertTrue(all(value["active"] is False for value in inactive))
        self.assertEqual(
            knowledge.load_topic_lifecycle_assessment_candidates(
                preferred_topic_ids=["sihixian_ecosystem"],
            ),
            [],
        )
        self.assertEqual(item["id"], "knowledge_sihixian_roster")

    def test_relationship_claim_recovers_to_l3_and_storage_rejects_lower_layer(self):
        self._curate_roster()
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            preferred_topic_ids=["sihixian_ecosystem"],
            limit=1,
        )[0]
        self.assertTrue(candidate["claims"][0]["has_relationships"])
        invalid = self._lifecycle_plan(candidate, layer="L2_CONTEXT")
        valid = self._lifecycle_plan(candidate, layer="L3_RELATIONSHIPS")
        model = Mock(side_effect=[invalid, valid])

        result = TopicLifecycleManager(model).run_once(
            preferred_topic_ids=["sihixian_ecosystem"]
        )

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["layered"], 1)
        self.assertEqual(model.call_count, 2)
        self.assertIn("_recovery.txt", model.call_args_list[1].args[0])
        topic = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertEqual(
            topic["claims"][0]["curation"]["knowledge_layer"],
            "L3_RELATIONSHIPS",
        )

        topic["claims"][0]["curation"].pop("knowledge_layer", None)
        topic["claims"][0]["curation"].pop("knowledge_layer_version", None)
        knowledge._save(knowledge._topic_path("sihixian_ecosystem"), topic)
        with self.assertRaisesRegex(
            ValueError,
            "topic_lifecycle_relationship_claim_not_l3",
        ):
            knowledge.apply_topic_lifecycle_assessment(invalid)


if __name__ == "__main__":
    unittest.main()
