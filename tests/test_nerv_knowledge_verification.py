import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import knowledge
from nerv.curiosity import CuriosityJournal
from nerv.knowledge_verification import CuriosityKnowledgeVerifier


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

    def test_evidence_gate_requires_two_independent_readable_sources(self):
        gate = CuriosityKnowledgeVerifier.evidence_gate(_search_result(1))
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["reason"], "insufficient_independent_evidence")

    def test_verdict_can_promote_only_after_evidence_gate(self):
        calls = []

        def model_call(_prompt, payload, **_kwargs):
            calls.append(json.loads(payload))
            return {
                "decision": "PROMOTE",
                "subject": "章鱼循环系统",
                "canonical_claim": "章鱼游泳时系统心脏会显著减慢。",
                "topics": ["章鱼", "动物生理"],
                "knowledge_type": "stable",
                "valid_for_days": None,
                "confidence": 0.92,
                "risk": "low",
                "reason": "两个独立来源支持该事实。",
            }

        verifier = CuriosityKnowledgeVerifier(model_call)
        verdict = verifier.evaluate(
            {"id": "curiosity-1", "question": "问题", "answer": "外部回答"},
            {"claim": "候选事实", "risk": "low"},
            _search_result(2),
        )
        self.assertEqual(verdict["decision"], "PROMOTE")
        self.assertTrue(verdict["evidence_gate"]["allowed"])
        self.assertEqual(len(calls), 1)
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
            "risk": "low",
        }

    @staticmethod
    def _verdict():
        return {
            "decision": "PROMOTE",
            "subject": "章鱼循环系统",
            "canonical_claim": "章鱼游泳时系统心脏会显著减慢。",
            "topics": ["章鱼", "动物生理"],
            "knowledge_type": "stable",
            "valid_for_days": None,
            "confidence": 0.92,
            "risk": "low",
            "reason": "独立来源形成一致证据。",
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
        self.assertEqual(item["verification_status"], "MULTI_SOURCE_CONSENSUS")
        self.assertEqual(item["provenance"]["external_ai_role"], "hypothesis_only")
        self.assertEqual(len(item["sources"]), 2)
        self.assertEqual(len(knowledge.load_active_items()), 1)

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
