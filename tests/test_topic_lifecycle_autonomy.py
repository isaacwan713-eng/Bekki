import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
from nerv import governance
from nerv.curiosity import CuriosityJournal
from nerv.knowledge_curator import KnowledgeCurator
from nerv.topic_lifecycle import TopicLifecycleManager


class TopicLifecycleAutonomyTests(unittest.TestCase):
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
    def _item(item_id, topic_id, claim, **updates):
        value = {
            "id": item_id,
            "subject": topic_id,
            "claim": claim,
            "topics": [topic_id],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": topic_id,
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.94,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
            "provenance": {"origin": "nerv_curiosity"},
        }
        value.update(updates)
        return value

    @staticmethod
    def _assignment(item, topic_id):
        subject_id = topic_id + "_subject"
        return {
            "knowledge_id": item["id"],
            "decision": "STORE",
            "topic_id": topic_id,
            "topic_title": topic_id,
            "topic_aliases": [],
            "topic_keywords": [topic_id],
            "subject_entity": {
                "id": subject_id,
                "name": item["subject"],
                "type": "subject",
                "aliases": [],
            },
            "literal_claim_subject": item["subject"],
            "selected_subject_entity_id": subject_id,
            "rejected_adjacent_entity_ids": [],
            "subject_selection_reason": "The claim names this exact subject.",
            "related_entities": [],
            "facet": "public_background",
            "claim_keywords": [topic_id],
            "preferred_display_claim": item["claim"],
            "preferred_display_language": "source",
            "name_rendering_status": "SOURCE_PRESERVED",
            "display_semantics_preserved": True,
            "related_claim_ids": [],
            "entity_scope_preserved": True,
            "relationship_semantics_consistent": True,
            "reason": "The claim belongs to this topic ecosystem.",
        }

    def _create_topic(self, topic_id, claims):
        existing = knowledge.load_items()
        knowledge._save_knowledge(existing + claims)
        assignments = [self._assignment(item, topic_id) for item in claims]
        counts = knowledge.apply_curator_assignments(assignments)
        self.assertEqual(counts["curated"], len(claims))

    @staticmethod
    def _coverage(claim_ids, active=False):
        rows = []
        for layer in knowledge.KNOWLEDGE_LAYERS:
            if layer == "L1_FOUNDATION":
                status = "COVERED"
                required = True
                evidence = claim_ids[:1]
            elif layer == "L2_CONTEXT" and active:
                status = "MISSING"
                required = True
                evidence = []
            else:
                status = "NOT_NEEDED"
                required = False
                evidence = []
            rows.append({
                "layer": layer,
                "status": status,
                "required_for_current_goal": required,
                "evidence_claim_ids": evidence,
                "reason": "Coverage follows the supplied verified claims.",
            })
        return rows

    @classmethod
    def _assessment(cls, candidate, active=False, interest=0.8):
        pending = candidate["pending_layer_claim_ids"]
        claim_ids = [item["knowledge_id"] for item in candidate["claims"]]
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
                        "L1_FOUNDATION" if index == 0 else "L2_CONTEXT"
                    ),
                    "reason": "This is the proposition's current depth.",
                }
                for index, knowledge_id in enumerate(pending)
            ],
            "topic_classification": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domain": "culture_entertainment",
                "category_path": [
                    {
                        "id": "public_culture",
                        "label": "公共文化",
                    },
                    {
                        "id": "cultural_topics",
                        "label": "文化主题",
                    },
                ],
                "reason": "The topic is public cultural knowledge.",
            },
            "claim_classifications": [
                {
                    "knowledge_id": knowledge_id,
                    "fact_type": (
                        "RELATIONSHIP"
                        if next(
                            (
                                value.get("has_relationships") is True
                                for value in candidate["claims"]
                                if value.get("knowledge_id") == knowledge_id
                            ),
                            False,
                        )
                        else "IDENTITY_DEFINITION"
                    ),
                    "reason": "This describes the proposition's fact shape.",
                }
                for knowledge_id in candidate.get(
                    "pending_classification_claim_ids", []
                )
            ],
            "target_layer": "L2_CONTEXT" if active else "L1_FOUNDATION",
            "coverage": cls._coverage(claim_ids, active=active),
            "completion_score": 0.62 if active else 0.9,
            "confidence": 0.93,
            "state": "ACTIVE" if active else "PAUSED_COMPLETE",
            "next_focus": "补充一个不同的基础背景。" if active else "",
            "pause_reason": "当前兴趣目标已经覆盖。" if not active else "",
            "interest_score": interest,
            "interest_basis": "The supplied curiosity signal sets priority.",
            "refresh_after_days": None if active else 30,
            "reason": "The state follows verified coverage and current interest.",
        }

    def _journal(self, model_call):
        return CuriosityJournal(
            model_call=model_call,
            unload_model=lambda _name: None,
            base_dir=self.project,
        )

    def _bind_verified_interest(self, journal, item, topic_id, score):
        state = journal.load()
        state["items"].append({
            "id": "curiosity_" + item["id"],
            "state": "VERIFIED",
            "question": "关于" + topic_id + "的已验证问题？",
            "interest_score": score,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "verification": {"knowledge_id": item["id"]},
        })
        governance.save_json(journal.path, state)
        journal.bind_curated_knowledge(
            knowledge.topic_links_for_knowledge_ids([item["id"]])
        )

    def test_verified_curiosity_is_layered_then_paused_without_followup(self):
        item = self._item(
            "knowledge_topic_alpha",
            "主题甲",
            "主题甲是一项公开文化主题。",
        )
        self._create_topic("topic_alpha", [item])

        def model(prompt, payload, **_kwargs):
            self.assertEqual(prompt, "prompts/nerv_topic_lifecycle.txt")
            packet = json.loads(payload)
            return self._assessment(packet["topic"], active=False, interest=0.91)

        journal = self._journal(model)
        self._bind_verified_interest(journal, item, "topic_alpha", 0.91)
        manager = TopicLifecycleManager(model, curiosity_journal=journal)
        result = manager.run_once(preferred_topic_ids=["topic_alpha"])

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["assessed"], 1)
        self.assertEqual(result["curiosity_seed"]["reason"], "no_topic_seed_due")
        topic = knowledge.load_topic_document("topic_alpha")
        self.assertEqual(topic["lifecycle"]["state"], "PAUSED_COMPLETE")
        self.assertEqual(
            topic["claims"][0]["curation"]["knowledge_layer"],
            "L1_FOUNDATION",
        )
        raw = knowledge.load_items()[0]
        self.assertEqual(raw["curation"]["knowledge_layer"], "L1_FOUNDATION")
        self.assertEqual(journal.load()["items"][0]["topic_id"], "topic_alpha")
        self.assertFalse(manager.due())

    def test_two_active_topics_seed_only_the_most_interesting_gap(self):
        high = self._item("knowledge_high", "高兴趣主题", "高兴趣主题已有基础知识。")
        low = self._item("knowledge_low", "低兴趣主题", "低兴趣主题已有基础知识。")
        self._create_topic("topic_high", [high])
        self._create_topic("topic_low", [low])

        def model(prompt, payload, **_kwargs):
            packet = json.loads(payload)
            if prompt == "prompts/nerv_topic_lifecycle.txt":
                candidate = packet["topic"]
                interest = 0.94 if candidate["topic_id"] == "topic_high" else 0.55
                return self._assessment(candidate, active=True, interest=interest)
            self.assertEqual(prompt, "prompts/nerv_curiosity_writer.txt")
            knowledge_id = packet["active_topic_knowledge"][0]["id"]
            return {
                "proposal": {
                    "question": "高兴趣主题还有哪个不同的基础背景值得了解？",
                    "reason": "这个未覆盖方向最符合当前兴趣。",
                    "trigger_summary": "高兴趣主题的基础背景。",
                    "interest_score": 0.94,
                    "confidence": 0.92,
                    "sharing_risk": "NORMAL",
                    "topic_stage": "DEVELOPING",
                    "current_turn_depth": "FOUNDATION",
                    "question_depth": "FOUNDATION",
                    "foundation_facet": "OTHER_CONCRETE_CONTEXT",
                    "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                    "breadth_fit": True,
                    "related_curiosity_ids": [],
                    "related_knowledge_ids": [knowledge_id],
                    "depth_fit": True,
                }
            }

        journal = self._journal(model)
        manager = TopicLifecycleManager(model, curiosity_journal=journal)
        result = manager.run_once()

        self.assertEqual(result["assessed"], 2)
        self.assertEqual(result["curiosity_seed"]["status"], "drafted")
        self.assertEqual(result["curiosity_seed"]["topic_id"], "topic_high")
        drafts = [item for item in journal.load()["items"] if item["state"] == "DRAFT"]
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["topic_id"], "topic_high")
        self.assertEqual(drafts[0]["seed_kind"], "TOPIC_GAP")
        self.assertFalse(manager.due())

    def test_due_paused_topics_refresh_only_highest_interest(self):
        high = self._item("knowledge_refresh_high", "刷新甲", "刷新甲已有已验证背景。")
        low = self._item("knowledge_refresh_low", "刷新乙", "刷新乙已有已验证背景。")
        self._create_topic("refresh_high", [high])
        self._create_topic("refresh_low", [low])
        empty_interest = TopicLifecycleManager._interest_fingerprint([])
        for topic_id, interest in (("refresh_high", 0.93), ("refresh_low", 0.51)):
            candidate = knowledge.load_topic_lifecycle_assessment_candidates(
                preferred_topic_ids=[topic_id],
                limit=1,
            )[0]
            assessment = self._assessment(candidate, active=False, interest=interest)
            assessment["_interest_fingerprint"] = empty_interest
            knowledge.apply_topic_lifecycle_assessment(assessment)
            document = knowledge.load_topic_document(topic_id)
            document["lifecycle"]["refresh"]["due_at"] = (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat()
            knowledge._save(knowledge._topic_path(topic_id), document)

        def model(prompt, payload, **_kwargs):
            self.assertEqual(prompt, "prompts/nerv_curiosity_writer.txt")
            packet = json.loads(payload)
            knowledge_id = packet["active_topic_knowledge"][0]["id"]
            return {
                "proposal": {
                    "question": "刷新甲自上次验证后出现了哪些值得更新的公开变化？",
                    "reason": "它是当前到期主题中最感兴趣的一个。",
                    "trigger_summary": "刷新甲的定期复查。",
                    "interest_score": 0.93,
                    "confidence": 0.92,
                    "sharing_risk": "NORMAL",
                    "topic_stage": "SUSTAINED",
                    "current_turn_depth": "FOUNDATION",
                    "question_depth": "FOUNDATION",
                    "foundation_facet": "OTHER_CONCRETE_CONTEXT",
                    "breadth_relation": "PROPORTIONATE_DEEPENING",
                    "breadth_fit": True,
                    "related_curiosity_ids": [],
                    "related_knowledge_ids": [knowledge_id],
                    "depth_fit": True,
                }
            }

        journal = self._journal(model)
        manager = TopicLifecycleManager(model, curiosity_journal=journal)
        self.assertTrue(manager.due())
        result = manager.run_once()

        self.assertEqual(result["curiosity_seed"]["topic_id"], "refresh_high")
        self.assertEqual(result["curiosity_seed"]["seed_kind"], "TOPIC_REFRESH")
        self.assertEqual(result["curiosity_seed"]["wake_reason"], "AUTO_INTEREST_REFRESH")
        self.assertEqual(len(journal.open_lifecycle_topic_ids()), 1)
        self.assertFalse(manager.due())

    def test_reviewable_claim_wakes_paused_topic_before_expiry(self):
        now = datetime.now(timezone.utc)
        item = self._item(
            "knowledge_review_due",
            "临期主题",
            "临期主题有一项需要定期复核的公开状态。",
            knowledge_type="reviewable",
            valid_for_days=30,
            expires_at=(now + timedelta(days=6)).isoformat(),
        )
        self._create_topic("review_due", [item])
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            preferred_topic_ids=["review_due"],
            limit=1,
        )[0]
        assessment = self._assessment(candidate, active=False, interest=0.76)
        assessment["_interest_fingerprint"] = (
            TopicLifecycleManager._interest_fingerprint([])
        )
        knowledge.apply_topic_lifecycle_assessment(assessment)

        seeds = knowledge.load_topic_refresh_candidates(now=now, limit=3)

        self.assertEqual([seed["topic_id"] for seed in seeds], ["review_due"])
        self.assertEqual(seeds[0]["wake_reason"], "REVIEW_DUE")

    def test_user_reengagement_can_reopen_a_paused_topic(self):
        item = self._item(
            "knowledge_reengaged",
            "重新关注主题",
            "重新关注主题已有一项已验证背景。",
        )
        self._create_topic("topic_reengaged", [item])
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            preferred_topic_ids=["topic_reengaged"],
            limit=1,
        )[0]
        assessment = self._assessment(candidate, active=False, interest=0.74)
        assessment["_interest_fingerprint"] = (
            TopicLifecycleManager._interest_fingerprint([])
        )
        knowledge.apply_topic_lifecycle_assessment(assessment)
        curated = knowledge.load_curated_items()[0]

        def model(prompt, payload, **_kwargs):
            self.assertEqual(prompt, "prompts/nerv_curiosity_writer.txt")
            packet = json.loads(payload)
            self.assertEqual(
                packet["active_topic_knowledge"][0]["topic_lifecycle_state"],
                "PAUSED_COMPLETE",
            )
            return {
                "proposal": {
                    "question": "重新关注主题还有哪个不同的基础背景值得了解？",
                    "reason": "用户重新提起了这个公开主题。",
                    "trigger_summary": "用户重新关注已暂停主题。",
                    "interest_score": 0.9,
                    "confidence": 0.92,
                    "sharing_risk": "NORMAL",
                    "topic_stage": "DEVELOPING",
                    "current_turn_depth": "FOUNDATION",
                    "question_depth": "FOUNDATION",
                    "foundation_facet": "OTHER_CONCRETE_CONTEXT",
                    "breadth_relation": "DISTINCT_FOUNDATION_FACET",
                    "breadth_fit": True,
                    "related_curiosity_ids": [],
                    "related_knowledge_ids": [item["id"]],
                    "depth_fit": True,
                }
            }

        journal = self._journal(model)
        result = journal.observe_turn(
            "我又想聊聊重新关注主题。",
            "可以，我们接着聊。",
            "LOCAL_ANSWER",
            knowledge_candidates=[curated],
        )

        self.assertEqual(result["status"], "drafted")
        draft = journal.load()["items"][0]
        self.assertEqual(draft["topic_id"], "topic_reengaged")
        self.assertEqual(draft["topic_lifecycle_state"], "PAUSED_COMPLETE")
        self.assertEqual(draft["wake_reason"], "USER_REENGAGEMENT")

    def test_pause_with_a_required_gap_is_rejected(self):
        item = self._item("knowledge_invalid_pause", "主题丙", "主题丙已有基础知识。")
        self._create_topic("topic_invalid", [item])
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(limit=1)[0]
        invalid = self._assessment(candidate, active=False)
        invalid["coverage"][1].update({
            "status": "MISSING",
            "required_for_current_goal": True,
        })

        assessment, errors = TopicLifecycleManager._validate_plan(invalid, candidate)

        self.assertIsNone(assessment)
        self.assertIn("pause_with_required_gap", errors)

    def test_layer_batches_finish_before_topic_can_pause(self):
        items = [
            self._item(
                "knowledge_batch_" + str(index),
                "分层批次主题",
                "这是第" + str(index) + "条已验证知识。",
            )
            for index in range(9)
        ]
        self._create_topic("layer_batch", items)
        calls = {"count": 0}

        def model(prompt, payload, **_kwargs):
            self.assertEqual(prompt, "prompts/nerv_topic_lifecycle.txt")
            candidate = json.loads(payload)["topic"]
            calls["count"] += 1
            return self._assessment(
                candidate,
                active=candidate["pending_layer_total"] > 8,
                interest=0.7,
            )

        manager = TopicLifecycleManager(model)
        first = manager.run_once(preferred_topic_ids=["layer_batch"])
        self.assertEqual(first["assessments"][0]["remaining_unlayered"], 1)
        self.assertEqual(
            knowledge.load_topic_document("layer_batch")["lifecycle"]["state"],
            "ACTIVE",
        )
        self.assertTrue(manager.due())

        second = manager.run_once(preferred_topic_ids=["layer_batch"])
        self.assertEqual(second["assessments"][0]["remaining_unlayered"], 0)
        self.assertEqual(
            knowledge.load_topic_document("layer_batch")["lifecycle"]["state"],
            "PAUSED_COMPLETE",
        )
        self.assertEqual(calls["count"], 2)
        self.assertFalse(manager.due())

    def test_curator_finishes_topic_layering_in_same_idle_pass(self):
        item = self._item(
            "knowledge_end_to_end",
            "topic_end_to_end",
            "topic_end_to_end has one foundational fact.",
        )
        knowledge._save_knowledge([item])

        def model(prompt, payload, **_kwargs):
            packet = json.loads(payload)
            if prompt == "prompts/nerv_daily_knowledge_curator.txt":
                return {
                    "curation_fingerprint": packet[
                        "required_curation_fingerprint"
                    ],
                    "assignments": [self._assignment(item, "topic_end_to_end")],
                    "reason": "Store the verified fact first.",
                }
            if prompt == "prompts/nerv_topic_lifecycle.txt":
                return self._assessment(packet["topic"], active=False, interest=0.8)
            self.fail("Unexpected model call: " + prompt)

        journal = self._journal(model)
        manager = TopicLifecycleManager(model, curiosity_journal=journal)
        curator = KnowledgeCurator(
            model,
            topic_lifecycle=manager,
            curiosity_journal=journal,
        )
        result = curator.run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["topic_autonomy"]["assessed"], 1)
        self.assertEqual(result["topic_autonomy"]["layered"], 1)
        self.assertEqual(
            knowledge.load_topic_document("topic_end_to_end")["lifecycle"]["state"],
            "PAUSED_COMPLETE",
        )

    def test_uncurated_verified_knowledge_cannot_start_an_idle_chain(self):
        journal = self._journal(lambda *_args, **_kwargs: self.fail("model called"))
        result = journal.observe_verified_knowledge(
            {
                "id": "knowledge_waiting",
                "status": "verified",
                "subject": "等待整理",
                "claim": "这条知识已经验证但尚未整理。",
            },
            {"id": "curiosity_waiting", "question": "一个问题？"},
        )
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["reason"], "awaiting_topic_curation")


if __name__ == "__main__":
    unittest.main()
