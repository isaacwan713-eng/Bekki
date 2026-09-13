import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import knowledge
import social_browser
from casper import browser
from nerv import external_fact_fallback
from nerv.knowledge_curator import (
    CURATOR_FAILURE_RETRY_SECONDS,
    KnowledgeCurator,
)


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class BilibiliOfficialIdentityTests(unittest.TestCase):
    def test_profile_search_has_a_distinct_native_url(self):
        url = social_browser.social_search_url(
            "bilibili", "四禧丸子", search_kind="profile"
        )
        self.assertIn("search.bilibili.com/upuser?", url)

    def test_descriptive_entity_scope_keeps_the_literal_quoted_name(self):
        self.assertEqual(
            browser._native_official_entity_expression(
                "四禧丸子 官方账号",
                "the group or project known as '四禧丸子'",
            ),
            "四禧丸子",
        )

    def test_video_author_link_is_not_a_profile_result(self):
        class Frame:
            def evaluate(self, _script):
                return [
                    {
                        "url": "https://space.bilibili.com/999",
                        "visible_text": "普通视频 UP主 蜘蛛侠_Official",
                        "image_url": "https://i0.hdslb.com/avatar.jpg",
                        "source_kind": "result_card",
                        "dom_card_matched": True,
                        "profile_result_matched": False,
                    },
                    {
                        "url": "https://www.bilibili.com/video/BV1safeproof",
                        "visible_text": "普通视频",
                        "image_url": "https://i0.hdslb.com/cover.jpg",
                        "source_kind": "result_card",
                        "dom_card_matched": True,
                        "author": "蜘蛛侠_Official",
                        "author_url": "https://space.bilibili.com/999",
                    },
                ]

        page = types.SimpleNamespace(frames=[Frame()])
        values = social_browser._extract_post_candidates(
            page, "bilibili", include_profile_candidates=True
        )
        self.assertEqual(len(values), 1)
        self.assertIn("/video/", values[0]["url"])

    def test_identity_requires_exact_characters_and_official_signal(self):
        base = {
            "url": "https://space.bilibili.com/123",
            "source_kind": "profile_result",
            "profile_result_matched": True,
            "profile_verified": False,
        }
        wrong_character = dict(
            base,
            profile_name="四喜丸子_Official",
            visible_text="四喜丸子_Official",
        )
        prefixed_clone = dict(
            base,
            profile_name="假四禧丸子_Official",
            visible_text="假四禧丸子_Official",
        )
        no_official_signal = dict(
            base,
            profile_name="四禧丸子",
            visible_text="四禧丸子 虚拟偶像团体",
        )
        verified = dict(
            base,
            profile_name="四禧丸子_Official+",
            visible_text="四禧丸子_Official+ 虚拟偶像团体",
        )
        self.assertIsNone(
            browser._bilibili_official_profile_proof(
                wrong_character, "四禧丸子"
            )
        )
        self.assertIsNone(
            browser._bilibili_official_profile_proof(
                prefixed_clone, "四禧丸子"
            )
        )
        self.assertIsNone(
            browser._bilibili_official_profile_proof(
                no_official_signal, "四禧丸子"
            )
        )
        proof = browser._bilibili_official_profile_proof(
            verified, "四禧丸子"
        )
        self.assertTrue(proof["official_identity_verified"])

    def test_unverified_identity_fails_closed_before_video_search(self):
        with patch.object(
            social_browser,
            "open_social_search",
            return_value={
                "url": "https://search.bilibili.com/upuser?keyword=x"
            },
        ) as opened, patch.object(
            social_browser,
            "inspect_active_social_page",
            return_value={
                "post_candidates": [{
                    "url": "https://space.bilibili.com/999",
                    "visible_text": "蜘蛛侠_Official",
                    "source_kind": "profile_result",
                    "profile_name": "蜘蛛侠_Official",
                    "profile_result_matched": True,
                }]
            },
        ), patch.object(
            social_browser, "close_social_search"
        ), patch.object(browser.time, "sleep", return_value=None):
            result = browser._discover_native_fixed_fact_candidates(
                "site:bilibili.com 四禧丸子 当前成员",
                ["bilibili.com"],
                official_only=True,
                entity_name="四禧丸子",
            )
        self.assertEqual(result["status"], "LIMITED_EVIDENCE")
        self.assertEqual(result["results"], [])
        self.assertEqual(opened.call_count, 1)

    def test_official_video_must_be_owned_by_the_proven_account(self):
        identity = {
            "publisher_name": "四禧丸子_Official+",
            "publisher_url": "https://space.bilibili.com/123",
        }
        self.assertTrue(browser._bilibili_candidate_owned_by_identity({
            "author": "四禧丸子_Official+",
            "author_url": "https://space.bilibili.com/123",
        }, identity))
        self.assertFalse(browser._bilibili_candidate_owned_by_identity({
            "author": "虎落平阳变北7",
            "author_url": "https://space.bilibili.com/999",
        }, identity))

    def test_ai_validator_cannot_bypass_missing_identity_proof(self):
        tools_stub = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=AssertionError("must not call AI"))
        )
        with patch.dict(sys.modules, {"tools": tools_stub}):
            result = browser._validate_candidate_answer(
                "四禧丸子 当前成员",
                {
                    "official_only": True,
                    "official_identity_verified": False,
                },
                "错误成员名单",
            )
        self.assertFalse(result["accepted"])
        tools_stub.run_ai_prompt.assert_not_called()


class KnowledgeRecoveryTests(unittest.TestCase):
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
    def _item(item_id, origin, proven=False):
        now = datetime.now(timezone.utc)
        return {
            "id": item_id,
            "subject": "四禧丸子",
            "claim": "官方公开的成员名单为：测试甲、测试乙、测试丙、测试丁。",
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
            "verification_status": "AI_PARTITIONED_AUDITED_FACT_LOOKUP",
            "verification": {
                "original_request": "请去B站核实四禧丸子，只看官方账号",
            },
            "sources": [{
                "title": "候选来源",
                "url": "https://www.bilibili.com/video/BV1legacy",
                "domain": "bilibili.com",
                "official_identity_verified": proven,
            }],
            "provenance": {"origin": origin},
        }

    def test_legacy_unproven_official_claim_is_quarantined_idempotently(self):
        wrong = self._item("knowledge_wrong", "casper_audited_fact_lookup")
        user_fact = self._item("knowledge_user", "user_provided")
        proven = self._item(
            "knowledge_proven", "casper_audited_fact_lookup", proven=True
        )
        knowledge._save(knowledge.KNOWLEDGE_FILE, [wrong, user_fact, proven])

        knowledge.initialize()
        first = {item["id"]: item for item in knowledge.load_items()}
        first_history_length = len(first["knowledge_wrong"]["revision_history"])
        knowledge.initialize()
        second = {item["id"]: item for item in knowledge.load_items()}

        self.assertEqual(first["knowledge_wrong"]["status"], "disputed")
        self.assertEqual(
            first["knowledge_wrong"]["verification_status"],
            "QUARANTINED_UNPROVEN_OFFICIAL_SOURCE",
        )
        self.assertEqual(first["knowledge_user"]["status"], "verified")
        self.assertEqual(first["knowledge_proven"]["status"], "verified")
        self.assertEqual(
            len(second["knowledge_wrong"]["revision_history"]),
            first_history_length,
        )
        active_ids = {item["id"] for item in knowledge.load_active_items()}
        self.assertNotIn("knowledge_wrong", active_ids)

    def test_proof_and_source_contract_are_persisted_with_new_claim(self):
        candidate = {
            "persist": True,
            "directly_supported_by_answer": True,
            "no_evidence_conflict": True,
            "subject": "四禧丸子",
            "claim": "官方公开的成员名单为：沐霂、又一、梨安、恬豆。",
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 180,
            "confidence": 0.95,
            "topics": ["四禧丸子"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "四禧丸子",
            "lifecycle_audit_status": "PASSED",
            "lifecycle_audit_reason": "Current roster is reviewable.",
            "partition_lifecycle_audit_version": (
                knowledge.PARTITION_LIFECYCLE_AUDIT_VERSION
            ),
        }
        search_result = {
            "status": "OK",
            "query": "四禧丸子 当前成员",
            "source_contract": {
                "source_scope": "FIXED_SITES",
                "requested_sites": ["bilibili.com"],
                "official_only": True,
            },
            "results": [{
                "title": "四禧丸子官方成员介绍",
                "url": "https://www.bilibili.com/video/BV1official",
                "domain": "bilibili.com",
                "official_identity_verified": True,
                "official_identity_basis": (
                    "bilibili_upuser_exact_entity_and_verified_badge"
                ),
                "publisher_name": "四禧丸子_Official+",
                "publisher_url": "https://space.bilibili.com/123",
                "official_publisher_page_bound": True,
                "official_publisher_video_discovery_version": 1,
            }],
            "answers": [],
        }
        status, item = knowledge.apply_verified_fact_lookup_partitioned_claim(
            "请去B站核实四禧丸子，只看官方账号",
            "成员为沐霂、又一、梨安、恬豆。",
            candidate,
            search_result,
        )
        self.assertEqual(status, "verified")
        self.assertTrue(item["sources"][0]["official_identity_verified"])
        self.assertTrue(
            item["sources"][0]["official_publisher_page_bound"]
        )
        self.assertEqual(
            item["sources"][0][
                "official_publisher_video_discovery_version"
            ],
            1,
        )
        self.assertEqual(
            item["verification"]["source_context"]["source_contract"],
            search_result["source_contract"],
        )


class LifecycleAndCuratorRecoveryTests(unittest.TestCase):
    def test_invisible_ai_date_cannot_turn_current_roster_into_history(self):
        item = {
            "id": "knowledge_current_roster",
            "subject": "四禧丸子",
            "claim": "官方公开的成员名单为：沐霂、又一、梨安、恬豆。",
            "knowledge_type": "stable",
            "valid_for_days": None,
            "confidence": 0.95,
            "temporal_scope": {
                "scope_type": "LATEST_COMPLETED_PERIOD",
                "requested_period": "2025-06-18",
                "allow_previous_period": False,
            },
        }
        invalid = {
            "decisions": [{
                "audit_id": item["id"],
                "persist": True,
                "lifecycle_basis": "FIXED_HISTORY",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "lifecycle_proportional": True,
                "reason": "Invented historical date.",
            }],
            "reason": "First audit.",
        }
        recovered = {
            "decisions": [{
                "audit_id": item["id"],
                "persist": True,
                "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
                "knowledge_type": "reviewable",
                "valid_for_days": 180,
                "lifecycle_proportional": True,
                "reason": "The visible claim is a current maintained roster.",
            }],
            "reason": "Recovered.",
        }
        with patch(
            "tools.run_ai_prompt", side_effect=[invalid, recovered]
        ) as model, patch("tools.unload_model"):
            decisions = external_fact_fallback.audit_existing_partition_lifecycles(
                [item]
            )
        self.assertEqual(model.call_count, 1)
        packet = json.loads(model.call_args_list[0].args[1])
        self.assertIsNone(packet["claims"][0]["temporal_scope"])
        self.assertTrue(packet["claims"][0]["current_people_roster"])
        self.assertEqual(decisions[0]["knowledge_type"], "reviewable")
        self.assertEqual(decisions[0]["valid_for_days"], 365)
        self.assertEqual(
            decisions[0]["partition_lifecycle_audit_version"],
            external_fact_fallback.PARTITION_LIFECYCLE_AUDIT_VERSION,
        )

    def test_roster_repair_uses_separate_subject_and_claim_evidence(self):
        evidence = {
            "knowledge_roster": {
                "subject": "四禧丸子",
                "claim": "官方公开的成员名单为：沐霂、又一、梨安、恬豆。",
            }
        }
        plan = {"assignments": [{
            "knowledge_id": "knowledge_roster",
            "decision": "STORE",
            "topic_id": "sihixian_ecosystem",
            "subject_entity": {
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "virtual_idol_group",
                "aliases": [],
            },
            "literal_claim_subject": "四禧丸子",
            "related_entities": [],
        }], "reason": "Repair literal roster."}
        repaired, repaired_ids = (
            KnowledgeCurator._repair_explicit_membership_relationships(
                plan, evidence, []
            )
        )
        relations = repaired["assignments"][0]["related_entities"]
        self.assertEqual(repaired_ids, ["knowledge_roster"])
        self.assertEqual({item["name"] for item in relations}, {
            "沐霂", "又一", "梨安", "恬豆"
        })
        self.assertTrue(all(
            item["relation_direction"] == "RELATED_TO_SUBJECT"
            for item in relations
        ))


class CuratorCooldownTests(unittest.TestCase):
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
        now = datetime.now(timezone.utc)
        knowledge._save_knowledge([{
            "id": "knowledge_pending",
            "subject": "待整理知识",
            "claim": "这是一条等待整理的稳定知识。",
            "topics": [],
            "knowledge_domain": "other",
            "cluster_label": "待整理知识",
            "learned_at": now.isoformat(),
            "confidence": 0.95,
            "knowledge_type": "stable",
            "valid_for_days": None,
            "expires_at": None,
            "risk": "low",
            "status": "verified",
            "verification_status": "VERIFIED",
            "provenance": {"origin": "nerv_curiosity"},
        }])

    def test_recent_failure_cools_down_but_old_failure_can_retry(self):
        knowledge.record_curator_run(
            "FAILED", details={"error": "invalid_curator_plan"}
        )
        curator = KnowledgeCurator(Mock())
        self.assertFalse(curator.due())

        payload = knowledge.load_curator_runs()
        old = (
            datetime.now(timezone.utc)
            - timedelta(seconds=CURATOR_FAILURE_RETRY_SECONDS + 60)
        ).isoformat()
        payload["runs"][-1]["recorded_at"] = old
        payload["last_attempt_at"] = old
        knowledge._save(knowledge._curator_runs_file(), payload)
        self.assertTrue(curator.due())


class PackagingContractTests(unittest.TestCase):
    def test_build_and_release_artifacts_are_current(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertTrue((
            ROOT
            / "TEST_BILIBILI_OFFICIAL_EVIDENCE_RECOVERY_V1_10_51_4.ps1"
        ).is_file())


if __name__ == "__main__":
    unittest.main()
