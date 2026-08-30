import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
import knowledge_retrieval
from nerv.knowledge_curator import KnowledgeCurator


class KnowledgeCuratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
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
    def _item(item_id, subject, claim, **updates):
        value = {
            "id": item_id,
            "subject": subject,
            "claim": claim,
            "topics": [],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": subject,
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.92,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "verification_status": "AI_PLUS_SOURCE_CORROBORATION",
            "provenance": {"origin": "nerv_curiosity"},
        }
        value.update(updates)
        return value

    @staticmethod
    def _assignment(item_id, subject_id, subject_name, **updates):
        value = {
            "knowledge_id": item_id,
            "decision": "STORE",
            "topic_id": "snh48",
            "topic_title": "SNH48",
            "topic_aliases": ["SNH", "塞纳河"],
            "topic_keywords": ["SNH48 GROUP", "偶像团体"],
            "subject_entity": {
                "id": subject_id,
                "name": subject_name,
                "type": "organization",
                "aliases": [],
            },
            "literal_claim_subject": subject_name,
            "selected_subject_entity_id": subject_id,
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": (
                "The selected entity is the primary subject named by the claim."
            ),
            "related_entities": [],
            "facet": "organization_structure",
            "claim_keywords": ["分队", "剧场"],
            "preferred_display_claim": subject_name,
            "preferred_display_language": "source",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "Belongs to the same public organization ecosystem.",
        }
        value.update(updates)
        return value

    def test_verified_curiosity_items_are_queued_and_grouped_in_one_ecosystem(self):
        first = self._item(
            "knowledge-snh-structure",
            "SNH48组织结构",
            "SNH48采用分队与剧场公演相结合的组织结构。",
        )
        second = self._item(
            "knowledge-member-history",
            "李艺彤与SNH48",
            "李艺彤曾是SNH48成员。",
        )
        knowledge._save_knowledge([first, second])
        self.assertEqual(len(knowledge.load_curation_inbox(pending_only=True)), 2)

        plan = {
            "assignments": [
                self._assignment(
                    first["id"], "snh48", "SNH48",
                    related_entities=[{
                        "id": "gnz48",
                        "name": "GNZ48",
                        "type": "organization",
                        "aliases": [],
                        "relation": "sister_group",
                        "claim_relation_evidence": (
                            "The claim places both organizations in one "
                            "sister-group ecosystem."
                        ),
                    }],
                ),
                self._assignment(
                    second["id"], "li_yitong", "李艺彤",
                    subject_entity={
                        "id": "li_yitong",
                        "name": "李艺彤",
                        "type": "person",
                        "aliases": [],
                    },
                    related_entities=[{
                        "id": "snh48",
                        "name": "SNH48",
                        "type": "organization",
                        "aliases": ["SNH"],
                        "relation": "former_member_of",
                        "claim_relation_evidence": "曾是SNH48成员",
                    }],
                    facet="membership_history",
                    claim_keywords=["李艺彤", "成员历史"],
                ),
            ],
            "reason": "Both claims belong to one ecosystem.",
        }
        model = Mock(return_value=plan)
        result = KnowledgeCurator(model).run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED")
        topic_path = Path(knowledge._topic_path("snh48"))
        topic = json.loads(topic_path.read_text(encoding="utf-8"))
        self.assertEqual(len(topic["claims"]), 2)
        self.assertEqual(set(topic["entities"]), {"snh48", "gnz48", "li_yitong"})
        self.assertEqual(
            {claim["curation"]["subject_entity_id"] for claim in topic["claims"]},
            {"snh48", "li_yitong"},
        )
        index = json.loads(
            Path(knowledge._topic_index_file()).read_text(encoding="utf-8")
        )
        self.assertEqual(index["terms"]["snh"], ["snh48"])
        self.assertEqual(index["terms"]["李艺彤"], ["snh48"])
        self.assertEqual(
            {
                item["id"]
                for item in knowledge_retrieval.shortlist("塞纳河组织如何运作？")
            },
            {first["id"], second["id"]},
        )
        self.assertFalse(KnowledgeCurator(model).due())

    def test_changing_current_fact_never_enters_curation_inbox(self):
        current = self._item(
            "knowledge-current-affiliation",
            "某人当前归属",
            "某人当前属于某团体。",
            knowledge_type="changing",
        )
        knowledge._save_knowledge([current])
        self.assertEqual(knowledge.load_curation_inbox(pending_only=True), [])

    def test_reviewable_item_is_queued_but_expired_item_is_not(self):
        active = self._item(
            "knowledge-reviewable-active",
            "组织结构",
            "组织当前采用四个长期分队。",
            knowledge_type="reviewable",
            valid_for_days=90,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=90)
            ).isoformat(),
        )
        expired = self._item(
            "knowledge-reviewable-expired",
            "旧组织结构",
            "组织过去采用另一结构。",
            knowledge_type="reviewable",
            valid_for_days=30,
            expires_at=(
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),
        )
        knowledge._save_knowledge([active, expired])
        pending_ids = {
            value["knowledge_id"]
            for value in knowledge.load_curation_inbox(pending_only=True)
        }
        self.assertEqual(pending_ids, {active["id"]})

    def test_pre_audit_mixed_claim_can_be_reclassified_as_reviewable(self):
        item = self._item(
            "knowledge-pre-audit-partition",
            "某组织正式单位",
            "该组织目前共有四个正式单位。",
            provenance={
                "origin": "external_ai_fact_fallback",
                "mixed_answer_partition": True,
            },
        )
        knowledge._save_knowledge([item])
        self.assertEqual(
            [
                value["id"]
                for value in knowledge.load_partition_lifecycle_audit_candidates()
            ],
            [item["id"]],
        )
        result = knowledge.apply_partition_lifecycle_reaudit([{
            "id": item["id"],
            "persist": True,
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "knowledge_type": "reviewable",
            "valid_for_days": 180,
            "lifecycle_proportional": True,
            "partition_lifecycle_audit_version": 7,
            "reason": "The present complete set can change occasionally.",
        }])
        self.assertEqual(result["reviewable"], 1)
        updated = knowledge.load_items()[0]
        self.assertEqual(updated["knowledge_type"], "reviewable")
        self.assertEqual(updated["valid_for_days"], 180)
        self.assertTrue(updated["expires_at"])
        self.assertEqual(
            updated["lifecycle_audit"]["basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(
            knowledge.load_partition_lifecycle_audit_candidates(), []
        )

    def test_lifecycle_basis_cannot_contradict_label_at_storage_boundary(self):
        item = self._item(
            "knowledge-basis-mismatch",
            "组织定义",
            "这是一个耐久定义。",
            provenance={
                "origin": "external_ai_fact_fallback",
                "mixed_answer_partition": True,
            },
        )
        knowledge._save_knowledge([item])
        with self.assertRaisesRegex(
            ValueError,
            "partition_lifecycle_basis_mismatch",
        ):
            knowledge.apply_partition_lifecycle_reaudit([{
                "id": item["id"],
                "persist": True,
                "lifecycle_basis": (
                    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                ),
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "partition_lifecycle_audit_version": 7,
                "reason": "Contradictory synthetic decision.",
            }])

    def test_partitioned_claim_cannot_bypass_independent_lifecycle_audit(self):
        assessment = {
            "decision": "ASK",
            "importance": "LOW",
            "sharing_risk": "NORMAL",
            "has_reusable_component": True,
        }
        candidate = {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "某组织正式单位",
            "claim": "该组织目前共有四个正式单位。",
            "knowledge_type": "reviewable",
            "valid_for_days": 180,
            "confidence": 0.92,
            "topics": ["组织结构"],
            "knowledge_domain": "business_organization",
            "cluster_label": "example_structure",
        }
        status, item = knowledge.apply_external_ai_partitioned_claim(
            "该组织目前有哪些正式单位？",
            "完整回答",
            assessment,
            candidate,
        )
        self.assertEqual((status, item), ("rejected", None))

        candidate.update({
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": "Present complete sets need review.",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "partition_lifecycle_audit_version": 7,
        })
        status, item = knowledge.apply_external_ai_partitioned_claim(
            "该组织目前有哪些正式单位？",
            "完整回答",
            assessment,
            candidate,
        )
        self.assertEqual(status, "verified")
        self.assertEqual(item["knowledge_type"], "reviewable")
        self.assertEqual(item["lifecycle_audit"]["status"], "PASSED")
        self.assertEqual(
            item["lifecycle_audit"]["basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )

    def test_fixed_history_partition_requires_exact_closed_period(self):
        assessment = {
            "decision": "ASK",
            "importance": "LOW",
            "sharing_risk": "NORMAL",
            "has_reusable_component": True,
        }
        candidate = {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "曼联历史阵容",
            "claim": "曼联2025赛季结束时的一线队阵容如答案所列。",
            "knowledge_type": "stable",
            "lifecycle_basis": "FIXED_HISTORY",
            "valid_for_days": None,
            "confidence": 0.92,
            "topics": ["曼联", "历史阵容"],
            "knowledge_domain": "sports",
            "cluster_label": "Manchester United",
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": "A completed season is fixed history.",
            "partition_lifecycle_audit_version": 7,
        }

        status, item = knowledge.apply_external_ai_partitioned_claim(
            "曼联2025赛季结束时的阵容？",
            "完整历史阵容答案。",
            assessment,
            candidate,
        )
        self.assertEqual((status, item), ("rejected", None))

        candidate["temporal_scope"] = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "completed 2025 season",
            "allow_previous_period": False,
        }
        status, item = knowledge.apply_external_ai_partitioned_claim(
            "曼联2025赛季结束时的阵容？",
            "完整历史阵容答案。",
            assessment,
            candidate,
        )
        self.assertEqual(status, "verified")
        self.assertEqual(
            item["temporal_scope"]["requested_period"],
            "completed 2025 season",
        )

    def test_curator_contract_keeps_different_period_snapshots_distinct(self):
        primary = Path(
            "prompts/nerv_daily_knowledge_curator.txt"
        ).read_text(encoding="utf-8")
        recovery = Path(
            "prompts/nerv_daily_knowledge_curator_recovery.txt"
        ).read_text(encoding="utf-8")
        for prompt in (primary, recovery):
            self.assertIn("temporal_scope", prompt)
            self.assertIn("different", prompt)
            self.assertIn("distinct", prompt)

    def test_daily_curator_automatically_repairs_pre_audit_mixed_claim(self):
        item = self._item(
            "knowledge-pre-audit-auto-repair",
            "某组织正式单位",
            "该组织目前共有四个正式单位。",
            provenance={
                "origin": "external_ai_fact_fallback",
                "mixed_answer_partition": True,
            },
        )
        knowledge._save_knowledge([item])
        knowledge.apply_curator_assignments([
            self._assignment(item["id"], "example_org", "示例组织")
        ])
        knowledge.record_curator_run(
            "COMPLETED",
            details={"processed": 1},
            local_date=KnowledgeCurator._local_date(),
        )
        plan = {
            "assignments": [
                self._assignment(item["id"], "example_org", "示例组织")
            ],
            "reason": "Re-curate corrected lifecycle metadata.",
        }
        curator = KnowledgeCurator(Mock(return_value=plan))
        self.assertTrue(curator.due())
        audit = [{
            "id": item["id"],
            "persist": True,
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "knowledge_type": "reviewable",
            "valid_for_days": 180,
            "lifecycle_proportional": True,
            "partition_lifecycle_audit_version": 7,
            "reason": "The present complete set can change occasionally.",
        }]
        with patch(
            "nerv.external_fact_fallback.audit_existing_partition_lifecycles",
            return_value=audit,
        ):
            result = curator.run_once()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["lifecycle_reaudit"]["reviewable"], 1)
        updated = knowledge.load_items()[0]
        self.assertEqual(updated["knowledge_type"], "reviewable")
        self.assertEqual(updated["partition_lifecycle_audit_version"], 7)
        self.assertFalse(curator.due())

    def test_browser_verified_correction_claim_has_source_provenance(self):
        candidate = {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "某组织正式单位",
            "claim": "该组织目前设有五个正式单位。",
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 365,
            "confidence": 0.94,
            "topics": ["组织结构"],
            "knowledge_domain": "business_organization",
            "cluster_label": "example_structure",
            "reason": "Accepted audited browser answer.",
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": "Maintained current set.",
            "partition_lifecycle_audit_version": 7,
        }
        status, item = knowledge.apply_verified_correction_partitioned_claim(
            "你之前的名单不对，请重新核实。",
            "该组织目前设有五个正式单位。",
            candidate,
            {
                "status": "OK",
                "query": "example official units",
                "discovery_type": "casper_search_summary_audited",
                "results": [{
                    "title": "Official structure",
                    "url": "https://example.test/structure",
                    "domain": "example.test",
                    "source_score": 95,
                }],
            },
        )

        self.assertEqual(status, "verified")
        self.assertEqual(item["source_domain"], "example.test")
        self.assertEqual(
            item["verification_status"],
            "AI_PARTITIONED_AUDITED_FACT_ANSWER",
        )
        self.assertEqual(
            item["provenance"]["origin"],
            "user_correction_fact_lookup",
        )
        self.assertIs(
            item["provenance"]["user_correction_is_evidence"],
            False,
        )
        self.assertEqual(len(item["sources"]), 1)

    def test_normal_fact_lookup_historical_snapshot_has_exact_provenance(self):
        exact_period = "2025 (specifically updated as of November 2025)"
        candidate = {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "Team SII 2025年11月成员快照",
            "claim": "截至2025年11月，Team SII成员包括示例成员甲和乙。",
            "knowledge_type": "stable",
            "lifecycle_basis": "FIXED_HISTORY",
            "valid_for_days": None,
            "confidence": 0.94,
            "topics": ["SNH48", "Team SII"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "temporal_scope": {
                "scope_type": "EXPLICIT_PERIOD",
                "requested_period": exact_period,
                "allow_previous_period": False,
            },
            "reason": "Accepted exact historical snapshot.",
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": "Closed historical roster snapshot.",
            "partition_lifecycle_audit_version": 7,
        }
        search_result = {
            "status": "OK",
            "query": "SNH48 Team SII members November 2025",
            "discovery_type": "casper_search_summary_audited",
            "answers": [{
                "accepted": True,
                "answer": candidate["claim"],
                "temporal_validation": {
                    "time_scope_match": True,
                    "source_period": exact_period,
                },
            }],
            "results": [{
                "title": "Official roster archive",
                "url": "https://example.test/roster-2025-11",
                "domain": "example.test",
                "source_score": 95,
                "published_at": "2025-11-30",
            }],
        }

        status, item = knowledge.apply_verified_fact_lookup_partitioned_claim(
            "2025年SNH48 Team SII有哪些成员？",
            candidate["claim"],
            candidate,
            search_result,
        )

        self.assertEqual(status, "verified")
        self.assertEqual(item["temporal_scope"]["requested_period"], exact_period)
        self.assertEqual(item["source_domain"], "example.test")
        self.assertEqual(
            item["verification_status"],
            "AI_PARTITIONED_AUDITED_FACT_LOOKUP",
        )
        self.assertEqual(
            item["provenance"]["origin"],
            "casper_audited_fact_lookup",
        )
        self.assertIs(item["provenance"]["knowledge_capture_after_reply"], True)
        self.assertEqual(item["sources"][0]["published_at"], "2025-11-30")

    def test_v1_wrongly_expired_mixed_structure_is_reaudited(self):
        item = self._item(
            "knowledge-v1-wrong-demotion",
            "某组织当前正式单位",
            "该组织目前共有四个正式单位。",
            status="expired",
            knowledge_type="changing",
            expires_at=datetime.now(timezone.utc).isoformat(),
            partition_lifecycle_audit_version=1,
            lifecycle_audit={
                "status": "PASSED",
                "reason": "Old auditor treated units as a roster.",
            },
            provenance={
                "origin": "external_ai_fact_fallback",
                "mixed_answer_partition": True,
            },
        )
        knowledge._save_knowledge([item])
        candidates = knowledge.load_partition_lifecycle_audit_candidates()
        self.assertEqual([value["id"] for value in candidates], [item["id"]])
        counts = knowledge.apply_partition_lifecycle_reaudit([{
            "id": item["id"],
            "persist": True,
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "knowledge_type": "reviewable",
            "valid_for_days": 180,
            "lifecycle_proportional": True,
            "partition_lifecycle_audit_version": 7,
            "reason": "Official unit sets are reusable structures.",
        }])
        self.assertEqual(counts["reviewable"], 1)
        repaired = knowledge.load_items()[0]
        self.assertEqual(repaired["status"], "verified")
        self.assertEqual(repaired["knowledge_type"], "reviewable")
        self.assertEqual(repaired["partition_lifecycle_audit_version"], 7)

    def test_v4_stable_mixed_structure_is_selected_for_v7_reaudit(self):
        item = self._item(
            "knowledge-v2-overstable-structure",
            "某组织当前正式单位",
            "该组织目前设有四个正式单位。",
            partition_lifecycle_audit_version=4,
            lifecycle_audit={
                "status": "PASSED",
                "reason": "Two earlier judges called the current set stable.",
            },
            provenance={
                "origin": "external_ai_fact_fallback",
                "mixed_answer_partition": True,
            },
        )
        knowledge._save_knowledge([item])
        candidates = knowledge.load_partition_lifecycle_audit_candidates()
        self.assertEqual([value["id"] for value in candidates], [item["id"]])

    def test_user_dispute_deactivates_claim_and_preserves_revision_history(self):
        original = self._item(
            "knowledge-user-disputed",
            "某组织正式单位",
            "该组织目前设有四个正式单位。",
            knowledge_type="reviewable",
            valid_for_days=365,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=365)
            ).isoformat(),
        )
        knowledge._save_knowledge([original])

        disputed = knowledge.mark_user_disputed_items(
            [original["id"]],
            "你说的这个不对，请重新核实。",
            reason="AI selected this exact public claim.",
        )

        self.assertEqual([item["id"] for item in disputed], [original["id"]])
        stored = knowledge.load_items()[0]
        self.assertEqual(stored["status"], "disputed")
        self.assertEqual(
            stored["dispute"]["status"],
            "PENDING_REVERIFICATION",
        )
        self.assertEqual(len(stored["revision_history"]), 1)
        self.assertEqual(
            stored["revision_history"][0]["claim"],
            original["claim"],
        )
        self.assertEqual(knowledge.load_active_items(), [])

        knowledge.mark_user_disputed_items(
            [original["id"]],
            "我仍然认为不对。",
        )
        self.assertEqual(
            len(knowledge.load_items()[0]["revision_history"]),
            1,
        )

    def test_reverified_replacement_supersedes_disputed_claim(self):
        original = self._item(
            "knowledge-old-claim",
            "某组织正式单位",
            "该组织目前设有四个正式单位。",
        )
        replacement = self._item(
            "knowledge-new-claim",
            "某组织正式单位",
            "该组织目前设有五个正式单位。",
            knowledge_type="reviewable",
            valid_for_days=365,
            expires_at=(
                datetime.now(timezone.utc) + timedelta(days=365)
            ).isoformat(),
            provenance={"origin": "external_ai_fact_fallback"},
        )
        knowledge._save_knowledge([original, replacement])
        knowledge.mark_user_disputed_items(
            [original["id"]],
            "你之前的数量不对。",
        )

        result = knowledge.resolve_user_dispute(
            [original["id"]],
            replacement_ids=[replacement["id"]],
            verified_answer=True,
            reason="Independent research produced a replacement.",
        )

        self.assertEqual(result["resolved"], 1)
        stored = {item["id"]: item for item in knowledge.load_items()}
        self.assertEqual(stored[original["id"]]["status"], "superseded")
        self.assertEqual(
            stored[original["id"]]["superseded_by"],
            [replacement["id"]],
        )
        self.assertEqual(
            stored[replacement["id"]]["provenance"][
                "supersedes_knowledge_ids"
            ],
            [original["id"]],
        )
        self.assertEqual(
            [item["id"] for item in knowledge.load_active_items()],
            [replacement["id"]],
        )

    def test_same_id_reverification_reactivates_without_erasing_history(self):
        original = self._item(
            "knowledge-refresh-same-id",
            "固定历史事实",
            "这条事实经过再次核实仍然正确。",
        )
        knowledge._save_knowledge([original])
        knowledge.mark_user_disputed_items(
            [original["id"]],
            "请再核实一次。",
        )

        knowledge.resolve_user_dispute(
            [original["id"]],
            replacement_ids=[original["id"]],
            verified_answer=True,
            reason="The same canonical record was refreshed.",
        )

        stored = knowledge.load_items()[0]
        self.assertEqual(stored["status"], "verified")
        self.assertEqual(
            stored["dispute"]["status"],
            "RESOLVED_REFRESHED",
        )
        self.assertEqual(len(stored["revision_history"]), 1)

    def test_conflict_is_quarantined_without_changing_verified_status(self):
        original = self._item(
            "knowledge-original",
            "组织结构",
            "该组织有四个正式分队。",
        )
        knowledge._save_knowledge([original])
        curator = KnowledgeCurator(Mock(return_value={
            "assignments": [self._assignment(
                original["id"], "example_org", "示例组织",
                topic_id="example_org",
                topic_title="示例组织",
            )],
            "reason": "Initial topic.",
        }))
        self.assertEqual(curator.run_once(force=True)["status"], "COMPLETED")

        conflicting = self._item(
            "knowledge-conflicting",
            "组织结构",
            "该组织没有正式分队。",
        )
        knowledge._save_knowledge([*knowledge.load_items(), conflicting])
        conflict_assignment = self._assignment(
            conflicting["id"], "example_org", "示例组织",
            decision="CONFLICT",
            topic_id="example_org",
            topic_title="示例组织",
            related_claim_ids=[original["id"]],
        )
        result = KnowledgeCurator(Mock(return_value={
            "assignments": [conflict_assignment],
            "reason": "Material contradiction.",
        })).run_once(force=True)
        self.assertEqual(result["conflict"], 1)
        raw = {item["id"]: item for item in knowledge.load_items()}
        self.assertEqual(raw[conflicting["id"]]["status"], "verified")
        self.assertEqual(
            raw[conflicting["id"]]["curation"]["status"], "conflict"
        )
        self.assertEqual(
            [item["id"] for item in knowledge.load_active_items()],
            [original["id"]],
        )

    def test_invalid_plan_retries_once_and_leaves_item_pending(self):
        item = self._item("knowledge-pending", "主题", "一条已验证知识。")
        knowledge._save_knowledge([item])
        invalid = {
            "assignments": [self._assignment(
                item["id"], "subject", "主题", topic_id="../unsafe"
            )],
            "reason": "Invalid path.",
        }
        model = Mock(side_effect=[invalid, invalid])
        result = KnowledgeCurator(model).run_once(force=True)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(model.call_count, 2)
        self.assertEqual(
            knowledge.load_curation_inbox(pending_only=True)[0]["knowledge_id"],
            item["id"],
        )

    def test_curator_grounding_fields_must_be_internally_consistent(self):
        knowledge_id = "knowledge-grounding-contract"
        catalog = [{
            "topic_id": "example-ecosystem",
            "entities": [
                {"id": "example", "name": "Example", "type": "organization"},
                {
                    "id": "example_group",
                    "name": "Example GROUP",
                    "type": "umbrella_organization",
                },
            ],
            "claims": [],
        }]
        valid = self._assignment(
            knowledge_id,
            "example",
            "Example",
            rejected_adjacent_entity_ids=["example_group"],
        )
        assignments, errors = KnowledgeCurator._validate_plan(
            {"assignments": [valid], "reason": "Grounded."},
            [knowledge_id],
            catalog,
        )
        self.assertIsNotNone(assignments, errors)

        mismatched = json.loads(json.dumps(valid))
        mismatched["selected_subject_entity_id"] = "example_group"
        assignments, errors = KnowledgeCurator._validate_plan(
            {"assignments": [mismatched], "reason": "Self-certified."},
            [knowledge_id],
            catalog,
        )
        self.assertIsNone(assignments)
        self.assertIn("selected_subject_id_mismatch", errors)

        missing_evidence = json.loads(json.dumps(valid))
        missing_evidence["related_entities"] = [{
            "id": "example_group",
            "name": "Example GROUP",
            "type": "umbrella_organization",
            "aliases": [],
            "relation": "part_of",
            "claim_relation_evidence": "",
        }]
        assignments, errors = KnowledgeCurator._validate_plan(
            {"assignments": [missing_evidence], "reason": "Self-certified."},
            [knowledge_id],
            catalog,
        )
        self.assertIsNone(assignments)
        self.assertIn("missing_claim_relation_evidence", errors)

    def test_backlog_is_curated_in_bounded_complete_batches(self):
        items = [
            self._item(
                "knowledge-batch-" + str(index),
                "主题" + str(index),
                "第" + str(index) + "条互不重复的已验证知识。",
            )
            for index in range(7)
        ]
        knowledge._save_knowledge(items)
        observed_batch_sizes = []

        def plan(_prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            batch = packet["already_verified_items"]
            observed_batch_sizes.append(len(batch))
            return {
                "assignments": [
                    self._assignment(
                        item["knowledge_id"],
                        "subject_" + item["knowledge_id"].rsplit("-", 1)[-1],
                        item["subject"],
                        topic_id="bounded_batch_topic",
                        topic_title="Bounded batch topic",
                        facet="fact_" + item["knowledge_id"].rsplit("-", 1)[-1],
                    )
                    for item in batch
                ],
                "reason": "Each batch is small enough to close its JSON.",
            }

        result = KnowledgeCurator(Mock(side_effect=plan)).run_once(force=True)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["processed"], 7)
        self.assertEqual(observed_batch_sizes, [3, 3, 1])
        self.assertEqual(knowledge.load_curation_inbox(pending_only=True), [])

    def test_topic_copy_cannot_outlive_authoritative_flat_ledger(self):
        item = self._item("knowledge-removable", "主题", "一条已验证知识。")
        knowledge._save_knowledge([item])
        plan = {
            "assignments": [self._assignment(
                item["id"], "example_topic", "示例主题",
                topic_id="example_topic",
                topic_title="示例主题",
            )],
            "reason": "Store once.",
        }
        self.assertEqual(
            KnowledgeCurator(Mock(return_value=plan)).run_once(force=True)["status"],
            "COMPLETED",
        )
        self.assertEqual(len(knowledge.load_active_items()), 1)
        knowledge._save_knowledge([], sync_curation=False)
        self.assertEqual(knowledge.load_active_items(), [])

    def test_curator_native_display_keeps_authoritative_claim_and_alias(self):
        item = self._item(
            "knowledge-native-name",
            "Chen Yuxuan",
            "In November 2025, Chen Yuxuan was a Team SII member.",
            temporal_scope={
                "scope_type": "EXPLICIT_PERIOD",
                "requested_period": "November 2025",
                "allow_previous_period": False,
                "closed_period": True,
            },
            verification={
                "original_question": "2025年Team SII有哪些成员？",
                "accepted_answer": "In November 2025, Chen Yuxuan was a Team SII member.",
            },
        )
        knowledge._save_knowledge([item])
        assignment = self._assignment(
            item["id"],
            "chen_yuxuan",
            "陈钰萱",
            subject_entity={
                "id": "chen_yuxuan",
                "name": "陈钰萱",
                "type": "person",
                "aliases": ["Chen Yuxuan"],
            },
            literal_claim_subject="Chen Yuxuan",
            selected_subject_entity_id="chen_yuxuan",
            preferred_display_claim=(
                "截至2025年11月，Team SII成员包括陈钰萱。"
            ),
            preferred_display_language="zh-Hans",
            name_rendering_status="NATIVE_PREFERRED",
            display_semantics_preserved=True,
            facet="historical_roster",
        )
        result = KnowledgeCurator(
            Mock(return_value={
                "assignments": [assignment],
                "reason": "Use the established Chinese display name.",
            })
        ).run_once(force=True)
        self.assertEqual(result["status"], "COMPLETED")
        stored = knowledge.load_active_items()[0]
        self.assertEqual(
            stored["claim"],
            "In November 2025, Chen Yuxuan was a Team SII member.",
        )
        self.assertEqual(
            stored["curation"]["preferred_display_claim"],
            "截至2025年11月，Team SII成员包括陈钰萱。",
        )
        topic = json.loads(
            Path(knowledge._topic_path("snh48")).read_text(encoding="utf-8")
        )
        self.assertIn("Chen Yuxuan", topic["entities"]["chen_yuxuan"]["aliases"])
        context = knowledge_retrieval.format_fast_context([stored])
        self.assertIn("陈钰萱", context)

    def test_new_item_after_today_curator_run_is_due_same_day(self):
        knowledge.record_curator_run(
            "COMPLETED",
            details={"processed": 0},
            local_date=KnowledgeCurator._local_date(),
        )
        self.assertFalse(KnowledgeCurator(Mock()).due())
        item = self._item(
            "knowledge-late-curiosity",
            "空闲好奇知识",
            "这是一条稍后由Curiosity验证的知识。",
        )
        knowledge._save_knowledge([item])
        self.assertTrue(KnowledgeCurator(Mock()).due())

    def test_curator_prompt_prefers_native_names_but_preserves_uncertain_source(self):
        project = Path(__file__).resolve().parents[1]
        for name in (
            "nerv_daily_knowledge_curator.txt",
            "nerv_daily_knowledge_curator_recovery.txt",
        ):
            prompt = (project / "prompts" / name).read_text(encoding="utf-8")
            self.assertIn("Chinese", prompt)
            self.assertIn("Japanese", prompt)
            self.assertIn("preserve", prompt.casefold())
            self.assertIn("romanized", prompt.casefold())

    def test_python_curator_has_no_domain_specific_snh_mapping(self):
        project = Path(__file__).resolve().parents[1]
        source = (
            (project / "knowledge.py").read_text(encoding="utf-8")
            + (project / "nerv" / "knowledge_curator.py").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("SNH48", source)
        self.assertNotIn("李艺彤", source)


if __name__ == "__main__":
    unittest.main()
