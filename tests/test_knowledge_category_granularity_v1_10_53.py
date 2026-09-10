import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
from nerv.topic_lifecycle import (
    TOPIC_CLASSIFICATION_SCHEMA,
    TopicLifecycleManager,
)


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class KnowledgeCategoryGranularityV11053Tests(unittest.TestCase):
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
    def _classification(
        path,
        granularity_version=0,
        domain="culture_entertainment",
    ):
        return {
            "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
            "granularity_version": granularity_version,
            "domain": domain,
            "category_path": deepcopy(path),
            "reason": "用于稳定浏览分类。",
            "classified_at": "2026-09-04T00:00:00+00:00",
        }

    def _store_topic(
        self,
        classification,
        state="PAUSED_COMPLETE",
        topic_id="sihixian_ecosystem",
        subject="四禧丸子",
        claim_text="四禧丸子是一个虚拟偶像团体。",
    ):
        now = datetime.now(timezone.utc)
        claim_id = "knowledge_category_" + topic_id
        claim = {
            "id": claim_id,
            "subject": subject,
            "claim": claim_text,
            "learned_at": now.isoformat(),
            "knowledge_type": "stable",
            "status": "verified",
            "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
            "curation": {
                "status": "curated",
                "topic_id": topic_id,
                "facet": "group_identity",
                "knowledge_layer": "L1_FOUNDATION",
                "knowledge_layer_version": knowledge.KNOWLEDGE_LAYER_VERSION,
                "fact_type": "IDENTITY_DEFINITION",
                "classification_version": (
                    knowledge.KNOWLEDGE_CLASSIFICATION_VERSION
                ),
            },
        }
        items = [
            item for item in knowledge.load_items()
            if isinstance(item, dict) and item.get("id") != claim_id
        ]
        items.append(claim)
        knowledge._save_knowledge(items, sync_curation=False)
        document = knowledge._empty_topic_document({
            "topic_id": topic_id,
            "topic_title": subject,
        })
        document["topic"]["keywords"] = ["虚拟偶像", "国风"]
        document["claims"] = [deepcopy(claim)]
        document["classification"] = deepcopy(classification)
        fingerprint = knowledge._topic_assessment_fingerprint(document)
        coverage = [
            {
                "layer": layer,
                "status": (
                    "COVERED" if layer == "L1_FOUNDATION" else "NOT_NEEDED"
                ),
                "required_for_current_goal": layer == "L1_FOUNDATION",
                "evidence_claim_ids": (
                    [claim["id"]] if layer == "L1_FOUNDATION" else []
                ),
                "reason": "当前目标只需要基础身份知识。",
            }
            for layer in knowledge.KNOWLEDGE_LAYERS
        ]
        document["lifecycle"] = {
            "version": knowledge.TOPIC_LIFECYCLE_VERSION,
            "state": state,
            "target_layer": "L1_FOUNDATION",
            "completion_score": 0.9,
            "confidence": 0.94,
            "coverage": coverage,
            "next_focus": "" if state == "PAUSED_COMPLETE" else "补充背景。",
            "pause_reason": (
                "当前目标已经覆盖。" if state == "PAUSED_COMPLETE" else ""
            ),
            "interest_score": 0.5,
            "interest_basis": "已有兴趣信号。",
            "assessment_fingerprint": fingerprint,
            "interest_fingerprint": TopicLifecycleManager._interest_fingerprint(
                []
            ),
            "assessed_at": "2026-09-04T00:00:00+00:00",
            "reason": "已有生命周期判断。",
            "refresh": {
                "after_days": 90 if state == "PAUSED_COMPLETE" else None,
                "due_at": (
                    (now + timedelta(days=90)).isoformat()
                    if state == "PAUSED_COMPLETE" else None
                ),
                "last_attempt_at": None,
                "last_attempt_status": None,
                "last_curiosity_id": None,
                "next_attempt_at": None,
            },
        }
        knowledge._save(
            knowledge._topic_path(topic_id),
            document,
        )
        knowledge._rebuild_topic_index()
        return deepcopy(document["lifecycle"])

    @staticmethod
    def _plan(candidate, path):
        lifecycle = candidate["existing_lifecycle"]
        refresh = lifecycle.get("refresh") or {}
        existing = candidate.get("existing_classification") or {}
        return {
            "assessment_contract_version": (
                knowledge.TOPIC_LIFECYCLE_ASSESSMENT_CONTRACT_VERSION
            ),
            "assessment_fingerprint": candidate["assessment_fingerprint"],
            "topic_id": candidate["topic_id"],
            "claim_layers": [],
            "topic_classification": {
                "version": knowledge.KNOWLEDGE_CLASSIFICATION_VERSION,
                "granularity_version": (
                    knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION
                ),
                "domain": existing.get("domain") or "culture_entertainment",
                "category_path": deepcopy(path),
                "reason": "保留大类并补充稳定子类。",
            },
            "claim_classifications": [],
            "target_layer": lifecycle["target_layer"],
            "coverage": deepcopy(lifecycle["coverage"]),
            "completion_score": lifecycle["completion_score"],
            "confidence": lifecycle["confidence"],
            "state": lifecycle["state"],
            "next_focus": lifecycle["next_focus"],
            "pause_reason": lifecycle["pause_reason"],
            "interest_score": lifecycle["interest_score"],
            "interest_basis": lifecycle["interest_basis"],
            "refresh_after_days": refresh.get("after_days"),
            "reason": lifecycle["reason"],
        }

    def test_build_and_two_level_contract_are_current(self):
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
        self.assertEqual(knowledge.KNOWLEDGE_CATEGORY_GRANULARITY_VERSION, 1)
        self.assertEqual(knowledge.KNOWLEDGE_CATEGORY_PATH_REQUIRED_DEPTH, 2)
        path_schema = TOPIC_CLASSIFICATION_SCHEMA["properties"]["category_path"]
        self.assertEqual(path_schema["minItems"], 2)
        self.assertEqual(path_schema["maxItems"], 2)
        self.assertIn("granularity_version", TOPIC_CLASSIFICATION_SCHEMA["required"])
        self.assertEqual(
            (ROOT / "knowledge.py").read_bytes(),
            (ROOT / "casper" / "knowledge.py").read_bytes(),
        )
        self.assertTrue(
            (ROOT / "TEST_KNOWLEDGE_CATEGORY_GRANULARITY_V1_10_53.ps1").is_file()
        )
        self.assertTrue(
            (ROOT / "KNOWLEDGE_CATEGORY_GRANULARITY_V1_10_53_NOTES.md").is_file()
        )

    def test_legacy_one_level_path_is_due_for_safe_refinement(self):
        path = [{"id": "music_entertainment", "label": "音乐娱乐"}]
        self._store_topic(self._classification(path))
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        self.assertTrue(candidate["classification_refinement_required"])
        self.assertTrue(candidate["classification_only_refinement"])
        self.assertEqual(candidate["pending_layer_claim_ids"], [])
        self.assertEqual(candidate["pending_classification_claim_ids"], [])

    def test_refinement_preserves_lifecycle_claim_and_layer(self):
        broad = {"id": "music_entertainment", "label": "音乐娱乐"}
        lifecycle_before = self._store_topic(self._classification([broad]))
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        plan = self._plan(candidate, [
            broad,
            {"id": "virtual_idols", "label": "虚拟偶像"},
        ])
        plan["_classification_only_refinement"] = True
        result = knowledge.apply_topic_lifecycle_assessment(plan)
        document = knowledge.load_topic_document("sihixian_ecosystem")
        self.assertTrue(result["category_refined"])
        self.assertTrue(result["classification_only_refinement"])
        self.assertEqual(document["lifecycle"], lifecycle_before)
        self.assertEqual(
            document["claims"][0]["claim"],
            "四禧丸子是一个虚拟偶像团体。",
        )
        self.assertEqual(
            document["claims"][0]["curation"]["knowledge_layer"],
            "L1_FOUNDATION",
        )
        self.assertEqual(
            document["classification"]["category_path"][1]["id"],
            "virtual_idols",
        )
        self.assertEqual(len(document["classification_history"]), 1)
        self.assertEqual(
            document["semantic_contract"]["category_granularity_version"],
            1,
        )

    def test_manager_refines_without_opening_a_new_curiosity_question(self):
        broad = {"id": "music_entertainment", "label": "音乐娱乐"}
        lifecycle_before = self._store_topic(self._classification([broad]))
        curiosity = Mock()
        curiosity.topic_interest_signals.return_value = []
        curiosity.open_lifecycle_topic_ids.return_value = []
        curiosity.open_topic_ids.return_value = []

        def model(_prompt, payload, **_kwargs):
            candidate = json.loads(payload)["topic"]
            return self._plan(candidate, [
                broad,
                {"id": "virtual_idols", "label": "虚拟偶像"},
            ])

        result = TopicLifecycleManager(
            model,
            curiosity_journal=curiosity,
        ).run_once()
        self.assertEqual(result["category_refined"], 1)
        self.assertEqual(
            knowledge.load_topic_document("sihixian_ecosystem")["lifecycle"],
            lifecycle_before,
        )
        curiosity.observe_topic_lifecycle.assert_not_called()

    def test_current_classification_is_locked_in_normal_lifecycle_run(self):
        current_path = [
            {"id": "music_entertainment", "label": "音乐娱乐"},
            {"id": "virtual_idols", "label": "虚拟偶像"},
        ]
        self._store_topic(self._classification(
            current_path,
            granularity_version=1,
        ))
        candidate = knowledge.load_topic_lifecycle_assessment_candidates(
            force_topic_ids=["sihixian_ecosystem"]
        )[0]
        changed = self._plan(candidate, [
            current_path[0],
            {"id": "idol_groups", "label": "真人偶像团体"},
        ])
        normalized, errors = TopicLifecycleManager._validate_plan(
            changed,
            candidate,
            category_catalog=knowledge.load_category_catalog(),
        )
        self.assertIsNone(normalized)
        self.assertIn("topic_classification_locked", errors)
        with self.assertRaisesRegex(ValueError, "topic_classification_locked"):
            knowledge.apply_topic_lifecycle_assessment(changed)

    def test_legacy_refinement_cannot_replace_the_established_prefix(self):
        broad = {"id": "music_entertainment", "label": "音乐娱乐"}
        self._store_topic(self._classification([broad]))
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        changed = self._plan(candidate, [
            {"id": "performing_arts", "label": "表演艺术"},
            {"id": "virtual_idols", "label": "虚拟偶像"},
        ])
        normalized, errors = TopicLifecycleManager._validate_plan(
            changed,
            candidate,
            category_catalog=knowledge.load_category_catalog(),
        )
        self.assertIsNone(normalized)
        self.assertIn(
            "topic_classification_refinement_prefix_changed",
            errors,
        )

    def test_five_live_topics_refine_into_three_reusable_paths(self):
        music = {"id": "music_entertainment", "label": "音乐娱乐"}
        robotics = {"id": "robotics_tech", "label": "机器人技术"}
        human_idols = {"id": "idol_groups", "label": "真人偶像团体"}
        virtual_idols = {"id": "virtual_idols", "label": "虚拟偶像"}
        open_robotics = {
            "id": "open_source_robotics",
            "label": "开源机器人",
        }
        topics = {
            "akb48_ecosystem": (
                "AKB48",
                "culture_entertainment",
                music,
                human_idols,
            ),
            "microduck_ecosystem": (
                "Microduck",
                "computer_science",
                robotics,
                open_robotics,
            ),
            "sihixian_ecosystem": (
                "四禧丸子",
                "culture_entertainment",
                music,
                virtual_idols,
            ),
            "snh48_group": (
                "SNH48",
                "culture_entertainment",
                music,
                human_idols,
            ),
            "twice_ecosystem": (
                "TWICE",
                "culture_entertainment",
                music,
                human_idols,
            ),
        }
        lifecycle_before = {}
        for topic_id, (title, domain, broad, _narrow) in topics.items():
            lifecycle_before[topic_id] = self._store_topic(
                self._classification([broad], domain=domain),
                topic_id=topic_id,
                subject=title,
                claim_text=title + " 是当前测试主题。",
            )

        curiosity = Mock()
        curiosity.topic_interest_signals.return_value = []
        curiosity.open_lifecycle_topic_ids.return_value = []
        curiosity.open_topic_ids.return_value = []

        def model(_prompt, payload, **_kwargs):
            candidate = json.loads(payload)["topic"]
            broad = candidate["existing_classification"]["category_path"][0]
            narrow = topics[candidate["topic_id"]][3]
            return self._plan(candidate, [broad, narrow])

        result = TopicLifecycleManager(
            model,
            curiosity_journal=curiosity,
        ).run_once()
        self.assertEqual(result["assessed"], 5)
        self.assertEqual(result["category_refined"], 5)
        self.assertEqual(result["failures"], [])
        for topic_id, (_title, _domain, broad, narrow) in topics.items():
            document = knowledge.load_topic_document(topic_id)
            self.assertEqual(
                document["classification"]["category_path"],
                [broad, narrow],
            )
            self.assertEqual(document["lifecycle"], lifecycle_before[topic_id])

        catalog = knowledge.load_category_catalog()
        catalog_by_path = {
            tuple(node["id"] for node in row["category_path"]): row
            for row in catalog
        }
        self.assertEqual(len(catalog_by_path), 3)
        self.assertEqual(
            catalog_by_path[("music_entertainment", "idol_groups")][
                "topic_ids"
            ],
            ["akb48_ecosystem", "snh48_group", "twice_ecosystem"],
        )
        curiosity.observe_topic_lifecycle.assert_not_called()

    def test_duplicate_sibling_ids_and_labels_are_rejected(self):
        catalog = [{
            "domain": "culture_entertainment",
            "category_path": [
                {"id": "music_entertainment", "label": "音乐娱乐"},
                {"id": "idol_groups", "label": "真人偶像团体"},
            ],
        }]
        base = [
            {"id": "music_entertainment", "label": "音乐娱乐"},
            {"id": "idol_group", "label": "偶像组合"},
        ]
        errors = knowledge.category_catalog_conflicts(
            self._classification(base, granularity_version=1),
            category_catalog=catalog,
        )
        self.assertIn("category_duplicate_id", errors)

        base[1] = {"id": "human_idols_v2", "label": "真人偶像团体"}
        errors = knowledge.category_catalog_conflicts(
            self._classification(base, granularity_version=1),
            category_catalog=catalog,
        )
        self.assertIn("category_duplicate_label", errors)

        base[1] = {"id": "idol_groups", "label": "网络主播"}
        errors = knowledge.category_catalog_conflicts(
            self._classification(base, granularity_version=1),
            category_catalog=catalog,
        )
        self.assertIn("category_label_mismatch", errors)

    def test_storage_boundary_rejects_duplicate_sibling_id(self):
        catalog = [{
            "domain": "culture_entertainment",
            "category_path": [
                {"id": "music_entertainment", "label": "音乐娱乐"},
                {"id": "idol_groups", "label": "真人偶像团体"},
            ],
        }]
        self._store_topic({})
        candidate = knowledge.load_topic_lifecycle_assessment_candidates()[0]
        plan = self._plan(candidate, [
            {"id": "music_entertainment", "label": "音乐娱乐"},
            {"id": "idol_group", "label": "偶像组合"},
        ])
        with patch.object(
            knowledge,
            "load_category_catalog",
            return_value=catalog,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "category_duplicate_id",
            ):
                knowledge.apply_topic_lifecycle_assessment(plan)


if __name__ == "__main__":
    unittest.main()
