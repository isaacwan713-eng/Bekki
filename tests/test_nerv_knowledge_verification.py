import tempfile
import unittest
import json
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

import knowledge
from nerv.curiosity import CuriosityJournal
from nerv.knowledge_verification import CuriosityKnowledgeVerifier


def _load_knowledge_retrieval():
    path = Path(__file__).resolve().parents[1] / "knowledge_retrieval.py"
    spec = importlib.util.spec_from_file_location(
        "knowledge_retrieval_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "knowledge": knowledge,
            "tools": types.SimpleNamespace(run_ai_prompt=lambda *_a, **_k: None),
        },
    ):
        spec.loader.exec_module(module)
    return module


def _search_result(source_count=2, consensus=True, votes=2):
    results = []
    for index in range(source_count):
        results.append({
            "title": "Source " + str(index + 1),
            "url": "https://source" + str(index + 1) + ".example/fact",
            "domain": "source" + str(index + 1) + ".example",
            "source_score": 90 - index,
            "page_success": True,
        })
    return {
        "status": "OK",
        "query": "octopus systemic heart swimming",
        "results": results,
        "answers": [
            {"index": index + 1, "answer": "Supported evidence."}
            for index in range(source_count)
        ],
        "judgment": {
            "consensus": consensus,
            "canonical_answer": "The systemic heart slows during swimming.",
            "votes": votes,
            "need_more_sources": False,
            "reason": "Independent sources agree.",
        },
    }


class CuriosityKnowledgeVerifierTests(unittest.TestCase):
    def test_candidate_treats_external_answer_as_hypothesis(self):
        calls = []

        def model_call(prompt_path, payload, **_kwargs):
            calls.append((prompt_path, payload))
            return {
                "decision": "VERIFY",
                "subject": "章鱼循环系统",
                "claim": "章鱼游泳时系统心脏会因喷射游泳的循环负担而显著减慢。",
                "topics": ["章鱼", "动物生理"],
                "knowledge_type": "stable",
                "valid_for_days": None,
                "risk": "low",
                "reason": "这是可独立核验的公共事实。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        result = verifier.prepare_candidate({
            "id": "curiosity-1",
            "question": "章鱼游泳时心脏为什么会停？",
            "answer": "系统心脏会停止或显著减慢。",
        })
        self.assertEqual(result["decision"], "VERIFY")
        self.assertIn("UNVERIFIED_EXTERNAL_AI", calls[0][1])

    def test_candidate_reason_cannot_relabel_wombat_as_koala(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: {
            "decision": "VERIFY",
            "subject": "袋熊的粪便",
            "claim": "袋熊的粪便呈方形。",
            "topics": ["动物生理"],
            "knowledge_type": "stable",
            "valid_for_days": None,
            "risk": "low",
            "reason": "This is a factual claim about koala feces.",
        })
        result = verifier.prepare_candidate({
            "id": "curiosity-wombat",
            "question": "袋熊的粪便是什么形状？",
            "answer": "外部回答。",
        })
        self.assertEqual(result["claim"], "袋熊的粪便呈方形。")
        self.assertEqual(
            result["reason"],
            "从外部回答中提取的核心候选事实，需要独立验证。",
        )

    def test_why_question_recovers_from_incidental_fact_to_core_mechanism(self):
        calls = []

        def model_call(prompt_path, _payload, **_kwargs):
            calls.append(prompt_path)
            if prompt_path.endswith("candidate.txt"):
                return {
                    "decision": "VERIFY",
                    "subject": "袋熊的肛门",
                    "claim": "袋熊的肛门呈圆形。",
                    "topics": ["动物生理"],
                    "knowledge_type": "changing",
                    "valid_for_days": 30,
                    "risk": "low",
                    "reason": "旁支事实。",
                }
            return {
                "decision": "VERIFY",
                "subject": "袋熊方形粪便的形成机制",
                "claim": "袋熊的方形粪便由肠道不同区域的弹性与收缩速度差异塑造。",
                "topics": ["动物生理", "消化系统"],
                "knowledge_type": "changing",
                "valid_for_days": 30,
                "risk": "low",
                "reason": "核心机制。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        result = verifier.prepare_candidate({
            "id": "curiosity-wombat",
            "question": "袋熊的粪便呈方形的原因是什么？",
            "answer": "方形在肠道内由不同弹性与收缩速度形成，肛门仍是圆形。",
        })
        self.assertEqual(result["decision"], "VERIFY")
        self.assertIn("肠道不同区域", result["claim"])
        self.assertEqual(result["knowledge_type"], "stable")
        self.assertIsNone(result["valid_for_days"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].endswith("candidate_recovery.txt"))

    def test_why_question_skips_when_recovery_is_still_incidental(self):
        def model_call(_prompt_path, _payload, **_kwargs):
            return {
                "decision": "VERIFY",
                "subject": "袋熊的肛门",
                "claim": "袋熊的肛门呈圆形。",
                "topics": ["动物生理"],
                "knowledge_type": "stable",
                "valid_for_days": None,
                "risk": "low",
                "reason": "旁支事实。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        result = verifier.prepare_candidate({
            "id": "curiosity-wombat",
            "question": "袋熊的粪便呈方形的原因是什么？",
            "answer": "外部回答。",
        })
        self.assertEqual(result["decision"], "SKIP")
        self.assertEqual(result["reason"], "causal_answer_required")

    def test_cjk_query_preserves_original_entity_without_model_translation(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: None)
        query = verifier.build_query(
            "袋熊的粪便呈方形",
            lambda _claim: self.fail("CJK claim must not use AI query translation"),
        )
        self.assertIn("袋熊", query)
        self.assertNotIn("koala", query.lower())

    def test_standard_cjk_query_uses_general_authoritative_sources(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: None)
        query = verifier.build_query(
            "SNH48采用分队与剧场公演相结合的组织结构",
            lambda _claim: self.fail("CJK claim must remain entity anchored"),
            "standard",
            "business_organization",
        )
        self.assertIn("SNH48", query)
        self.assertIn("官方资料", query)
        self.assertNotIn("scientific study", query)

    def test_candidate_policy_gate_skips_high_risk_claim(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: {
            "decision": "VERIFY",
            "subject": "健康",
            "claim": "一个医疗主张。",
            "topics": ["健康"],
            "knowledge_type": "stable",
            "valid_for_days": None,
            "risk": "high",
            "reason": "测试",
        })
        result = verifier.prepare_candidate({
            "id": "curiosity-1", "question": "问题", "answer": "回答"
        })
        self.assertEqual(result["decision"], "SKIP")

    def test_changing_roster_candidate_is_skipped_before_verification(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: {
            "decision": "VERIFY",
            "subject": "道奇当前阵容",
            "claim": "道奇当前名单包含某球员。",
            "topics": ["道奇", "阵容"],
            "knowledge_domain": "sports",
            "verification_level": "standard",
            "knowledge_type": "changing",
            "valid_for_days": 1,
            "risk": "low",
            "reason": "当前公开信息。",
        })
        result = verifier.prepare_candidate({
            "id": "curiosity-roster",
            "question": "道奇现在有谁？",
            "answer": "外部回答。",
        })
        self.assertEqual(result["decision"], "SKIP")
        self.assertEqual(result["reason"], "non_reusable_knowledge")

    def test_formal_unit_set_candidate_is_reviewable(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: {
            "decision": "VERIFY",
            "subject": "SNH48正式Team",
            "claim": "SNH48目前有四个正式Team。",
            "topics": ["SNH48", "正式Team"],
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "verification_level": "standard",
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 180,
            "risk": "low",
            "reason": "这是一个会偶尔变化的正式组织结构。",
        })
        result = verifier.prepare_candidate({
            "id": "curiosity-snh-teams",
            "question": "SNH48目前有哪些正式Team？",
            "answer": "外部回答列出了完整正式Team。",
        })
        self.assertEqual(result["decision"], "VERIFY")
        self.assertEqual(result["knowledge_type"], "reviewable")
        self.assertEqual(
            result["lifecycle_basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        self.assertEqual(result["valid_for_days"], 180)

    def test_medical_candidate_cannot_downgrade_double_verification(self):
        verifier = CuriosityKnowledgeVerifier(lambda *_args, **_kwargs: {
            "decision": "VERIFY",
            "subject": "基础医学事实",
            "claim": "这是一个稳定且非建议性的医学事实。",
            "topics": ["医学"],
            "knowledge_domain": "medical",
            "verification_level": "standard",
            "knowledge_type": "stable",
            "valid_for_days": None,
            "risk": "low",
            "reason": "基础事实。",
        })
        result = verifier.prepare_candidate({
            "id": "curiosity-medical",
            "question": "一个基础医学事实是什么？",
            "answer": "外部回答。",
        })
        self.assertEqual(result["decision"], "VERIFY")
        self.assertEqual(result["verification_level"], "double")

    def test_standard_verification_uses_external_answer_plus_one_source(self):
        calls = []

        def model_call(prompt, payload, **_kwargs):
            calls.append((prompt, json.loads(payload)))
            return {
                "decision": "PROMOTE",
                "subject": "SNH48组织结构",
                "canonical_claim": "SNH48采用分队与剧场公演结合的组织结构。",
                "topics": ["SNH48", "组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "SNH48",
                "verification_level": "standard",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.88,
                "risk": "low",
                "reason": "一个合格来源与外部回答一致。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        verdict = verifier.evaluate(
            {
                "id": "curiosity-snh48",
                "question": "SNH48的组织结构是什么？",
                "answer": "外部AI回答：采用分队和剧场公演。",
            },
            {
                "subject": "SNH48组织结构",
                "claim": "SNH48采用分队与剧场公演结合的组织结构。",
                "topics": ["SNH48", "组织结构"],
                "knowledge_domain": "business_organization",
                "cluster_label": "SNH48",
                "verification_level": "standard",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "risk": "low",
            },
            _search_result(1, consensus=False, votes=1),
        )
        self.assertEqual(verdict["decision"], "PROMOTE")
        self.assertEqual(len(calls), 1)
        self.assertIn(
            "外部AI回答",
            calls[0][1]["curiosity"]["external_ai_supporting_answer"],
        )

    def test_evidence_gate_requires_two_independent_readable_sources(self):
        gate = CuriosityKnowledgeVerifier.evidence_gate(_search_result(1))
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["reason"], "insufficient_independent_evidence")

    def test_verdict_can_promote_only_after_evidence_gate(self):
        calls = []

        def model_call(_prompt, payload, **_kwargs):
            calls.append(json.loads(payload))
            if _prompt.endswith("double_certify.txt"):
                return {
                    "decision": "CERTIFY",
                    "confidence": 0.94,
                    "reason": "Second evidence review supports the claim.",
                }
            return {
                "decision": "PROMOTE",
                "subject": "章鱼循环系统",
                "canonical_claim": "章鱼游泳时系统心脏会显著减慢。",
                "topics": ["章鱼", "动物生理"],
                "knowledge_domain": "medical",
                "verification_level": "double",
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.92,
                "risk": "low",
                "reason": "两个独立来源支持该事实。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        verdict = verifier.evaluate(
            {"id": "curiosity-1", "question": "问题", "answer": "外部回答"},
            {
                "claim": "候选事实",
                "risk": "low",
                "knowledge_domain": "medical",
                "verification_level": "double",
            },
            _search_result(2),
        )
        self.assertEqual(verdict["decision"], "PROMOTE")
        self.assertTrue(verdict["evidence_gate"]["allowed"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("external_ai_answer", calls[0]["curiosity"])
        self.assertNotIn("reason", calls[0]["candidate_hypothesis"])
        self.assertNotIn("reason", calls[0]["evidence_judgment"])

    def test_insufficient_evidence_never_calls_verdict_model(self):
        verifier = CuriosityKnowledgeVerifier(
            lambda *_args, **_kwargs: self.fail("verdict model should not run")
        )
        verdict = verifier.evaluate({}, {}, _search_result(1))
        self.assertEqual(verdict["decision"], "KEEP_UNVERIFIED")


class CuriosityKnowledgePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        patches = {
            "DATA_DIR": str(root),
            "KNOWLEDGE_FILE": str(root / "knowledge.json"),
            "SOURCES_FILE": str(root / "knowledge_sources.json"),
            "LOGS_FILE": str(root / "learning_logs.json"),
            "PENDING_SOURCES_FILE": str(root / "knowledge_source_candidates.json"),
        }
        patcher = patch.multiple(knowledge, **patches)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _candidate():
        return {
            "subject": "章鱼循环系统",
            "claim": "外部AI候选说法",
            "topics": ["章鱼", "动物生理"],
            "knowledge_type": "stable",
            "knowledge_domain": "medical",
            "verification_level": "double",
            "risk": "low",
        }

    @staticmethod
    def _verdict():
        return {
            "decision": "PROMOTE",
            "subject": "章鱼循环系统",
            "canonical_claim": "章鱼游泳时系统心脏会显著减慢。",
            "topics": ["章鱼", "动物生理"],
            "knowledge_domain": "medical",
            "verification_level": "double",
            "knowledge_type": "stable",
            "valid_for_days": None,
            "confidence": 0.92,
            "risk": "low",
            "reason": "独立来源形成一致证据。",
            "double_certification": {
                "decision": "CERTIFY",
                "confidence": 0.94,
                "reason": "第二次认证通过。",
            },
        }

    def test_verified_bundle_enters_knowledge_with_external_ai_as_hypothesis(self):
        status, item = knowledge.apply_curiosity_verification(
            self._candidate(),
            self._verdict(),
            _search_result(2),
            {"id": "curiosity-1"},
        )
        self.assertEqual(status, "verified")
        self.assertEqual(item["status"], "verified")
        self.assertEqual(
            item["verification_status"],
            "DOUBLE_CERTIFIED_MULTI_SOURCE",
        )
        self.assertEqual(item["provenance"]["external_ai_role"], "hypothesis_only")
        self.assertEqual(len(item["sources"]), 2)
        self.assertEqual(item["cluster"]["domain"], "medical")
        self.assertEqual(len(knowledge.load_clusters()["clusters"]), 1)
        self.assertEqual(len(knowledge.load_active_items()), 1)

    def test_standard_basic_fact_can_use_ai_plus_one_qualified_source(self):
        candidate = {
            "subject": "SNH48组织结构",
            "claim": "SNH48采用分队与剧场公演相结合的组织结构。",
            "topics": ["SNH48", "偶像团体", "组织结构"],
            "knowledge_type": "stable",
            "knowledge_domain": "business_organization",
            "cluster_label": "SNH48",
            "verification_level": "standard",
            "risk": "low",
        }
        verdict = {
            "decision": "PROMOTE",
            "subject": candidate["subject"],
            "canonical_claim": candidate["claim"],
            "topics": candidate["topics"],
            "knowledge_type": "stable",
            "knowledge_domain": "business_organization",
            "cluster_label": "SNH48",
            "verification_level": "standard",
            "valid_for_days": None,
            "confidence": 0.88,
            "risk": "low",
            "reason": "外部回答与一个合格来源一致。",
        }
        status, item = knowledge.apply_curiosity_verification(
            candidate,
            verdict,
            _search_result(1, consensus=False, votes=1),
            {"id": "curiosity-snh48"},
        )
        self.assertEqual(status, "verified")
        self.assertEqual(
            item["verification_status"],
            "AI_PLUS_SOURCE_CORROBORATION",
        )
        self.assertEqual(item["provenance"]["external_ai_role"], "corroborating_signal")
        retrieval = _load_knowledge_retrieval()
        with patch.object(retrieval.knowledge, "load_active_items", return_value=[item]):
            context = retrieval.fast_context(
                "我想开一个SNH48一样的公司，组织上应该优化什么？"
            )
        self.assertIn("SNH48组织结构", context)

    def test_changing_roster_can_never_enter_knowledge(self):
        candidate = dict(self._candidate())
        candidate.update({
            "subject": "道奇当前阵容",
            "claim": "道奇当前名单包含某球员。",
            "knowledge_type": "changing",
            "knowledge_domain": "sports",
            "verification_level": "standard",
        })
        verdict = dict(self._verdict())
        verdict.update({
            "subject": candidate["subject"],
            "canonical_claim": candidate["claim"],
            "knowledge_type": "changing",
            "knowledge_domain": "sports",
            "verification_level": "standard",
        })
        status, item = knowledge.apply_curiosity_verification(
            candidate,
            verdict,
            _search_result(2),
            {"id": "curiosity-roster"},
        )
        self.assertEqual(status, "unverified")
        self.assertIsNone(item)

    def test_reviewable_curiosity_structure_enters_knowledge_and_curation(self):
        candidate = {
            "subject": "SNH48正式Team",
            "claim": "SNH48目前有四个正式Team。",
            "topics": ["SNH48", "正式Team"],
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 180,
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "verification_level": "standard",
            "risk": "low",
        }
        verdict = {
            "decision": "PROMOTE",
            "subject": candidate["subject"],
            "canonical_claim": candidate["claim"],
            "topics": candidate["topics"],
            "knowledge_type": "reviewable",
            "lifecycle_basis": "MAINTAINED_SET_OR_STRUCTURE",
            "valid_for_days": 180,
            "knowledge_domain": "culture_entertainment",
            "cluster_label": "SNH48",
            "verification_level": "standard",
            "confidence": 0.9,
            "risk": "low",
            "reason": "外部答案与合格来源一致。",
        }
        status, item = knowledge.apply_curiosity_verification(
            candidate,
            verdict,
            _search_result(1, consensus=False, votes=1),
            {
                "id": "curiosity-snh-teams",
                "question": "SNH48目前有哪些正式Team？",
                "answer": "外部回答列出了完整正式Team。",
            },
        )
        self.assertEqual(status, "verified")
        self.assertEqual(item["knowledge_type"], "reviewable")
        self.assertIsNotNone(item["expires_at"])
        self.assertEqual(
            item["lifecycle_audit"]["basis"],
            "MAINTAINED_SET_OR_STRUCTURE",
        )
        pending_ids = {
            value["knowledge_id"]
            for value in knowledge.load_curation_inbox(pending_only=True)
        }
        self.assertIn(item["id"], pending_ids)

    def test_fixed_history_curiosity_snapshot_enters_knowledge(self):
        temporal_scope = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "2025年11月",
            "allow_previous_period": False,
        }
        candidate = {
            "subject": "示例联队2025年11月阵容",
            "claim": "截至2025年11月，示例联队成员为球员甲、球员乙。",
            "topics": ["示例联队", "历史阵容"],
            "knowledge_type": "stable",
            "lifecycle_basis": "FIXED_HISTORY",
            "valid_for_days": None,
            "temporal_scope": temporal_scope,
            "knowledge_domain": "sports",
            "cluster_label": "示例联队",
            "verification_level": "standard",
            "risk": "low",
        }
        verdict = {
            "decision": "PROMOTE",
            "subject": candidate["subject"],
            "canonical_claim": candidate["claim"],
            "topics": candidate["topics"],
            "knowledge_type": "stable",
            "lifecycle_basis": "FIXED_HISTORY",
            "valid_for_days": None,
            "temporal_scope": temporal_scope,
            "knowledge_domain": "sports",
            "cluster_label": "示例联队",
            "verification_level": "standard",
            "confidence": 0.9,
            "risk": "low",
            "reason": "这是已结束日期的固定历史快照。",
        }
        status, item = knowledge.apply_curiosity_verification(
            candidate,
            verdict,
            _search_result(1, consensus=False, votes=1),
            {
                "id": "curiosity-history-roster",
                "question": "2025年11月示例联队有哪些成员？",
                "answer": "外部回答列出了该月阵容。",
            },
        )
        self.assertEqual(status, "verified")
        self.assertEqual(item["lifecycle_audit"]["basis"], "FIXED_HISTORY")
        self.assertTrue(item["temporal_scope"]["closed_period"])
        self.assertIsNone(item["expires_at"])

    def test_one_source_cannot_enter_knowledge(self):
        status, item = knowledge.apply_curiosity_verification(
            self._candidate(),
            self._verdict(),
            _search_result(1),
            {"id": "curiosity-1"},
        )
        self.assertEqual(status, "unverified")
        self.assertIsNone(item)
        self.assertEqual(knowledge.load_active_items(), [])

    def test_journal_records_verified_knowledge_link(self):
        journal = CuriosityJournal(
            model_call=lambda *_args, **_kwargs: None,
            base_dir=Path(self.temporary.name),
        )
        state = journal.load()
        state["items"] = [{
            "id": "curiosity-1",
            "state": "ANSWERED_UNVERIFIED",
            "question": "章鱼游泳时心脏为什么会停？",
            "reason": "想理解适应机制。",
            "answer": "外部AI回答。",
            "created_at": "2026-08-26T00:00:00+00:00",
        }]
        journal.path.write_text(
            __import__("json").dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
        recorded = journal.record_verification_outcome(
            "curiosity-1",
            "VERIFIED",
            "两个来源一致。",
            claim="章鱼游泳时系统心脏会显著减慢。",
            sources=[{"title": "A", "domain": "a.example", "url": "https://a.example"}],
            knowledge_id="knowledge-1",
        )
        self.assertEqual(recorded["status"], "VERIFIED")
        reply, _ = journal.journal_reply("zh-CN")
        self.assertIn("已通过独立搜索验证并进入 Knowledge", reply)
        self.assertIn("章鱼游泳时系统心脏会显著减慢", reply)


if __name__ == "__main__":
    unittest.main()
