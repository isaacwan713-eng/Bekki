"""Turn an external-AI curiosity answer into an independently checked candidate."""

import json
import re
from copy import deepcopy

from .schemas import (
    CURIOSITY_KNOWLEDGE_CANDIDATE_SCHEMA,
    CURIOSITY_KNOWLEDGE_VERDICT_SCHEMA,
)


MIN_SOURCE_SCORE = 70
MIN_INDEPENDENT_SOURCES = 2
MIN_CONSENSUS_VOTES = 2
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_CAUSAL_QUESTION_RE = re.compile(
    r"(?:为什么|为何|如何|怎样|怎么|原因(?:是|是什么)?|什么原因|机制(?:是|是什么)?|"
    r"\bwhy\b|\bhow\b|\bwhat causes?\b|\bwhat mechanism\b)",
    re.IGNORECASE,
)
_CAUSAL_CLAIM_RE = re.compile(
    r"(?:因为|因(?=[\u3400-\u9fff])|由于|源于|起因于|取决于|通过|导致|造成|形成|塑造|使得|"
    r"与.+有关|由.+(?:产生|形成|造成|塑造)|"
    r"\bbecause\b|\bdue to\b|\bcaused by\b|\bresults? from\b|"
    r"\bthrough\b|\bmechanism\b)",
    re.IGNORECASE,
)
_TEMPORAL_QUESTION_RE = re.compile(
    r"(?:最近|近期|目前|现在|今年|本月|本周|今天|最新|当前|"
    r"\brecent(?:ly)?\b|\bcurrent(?:ly)?\b|\blatest\b|\btoday\b|"
    r"\bthis (?:year|month|week)\b)",
    re.IGNORECASE,
)


class CuriosityKnowledgeVerifier:
    """AI proposes semantics; Python owns the evidence and persistence gates."""

    def __init__(self, model_call, unload_model=None):
        self.model_call = model_call
        self.unload_model = unload_model

    def _release(self, stage):
        if self.unload_model is None:
            return
        try:
            self.unload_model("gemma3:12b")
            print("[NERV KNOWLEDGE MODEL RELEASED]", stage, "gemma3:12b")
        except Exception as error:
            print("[NERV KNOWLEDGE MODEL RELEASE WARNING]", stage, repr(error))

    @staticmethod
    def _item_packet(item):
        item = item if isinstance(item, dict) else {}
        return {
            "curiosity_id": str(item.get("id") or "")[:120],
            "question": str(item.get("question") or "")[:1200],
            "external_ai_answer": str(item.get("answer") or "")[:6000],
            "external_ai_status": "UNVERIFIED_EXTERNAL_AI",
            "trigger_summary": str(item.get("trigger_summary") or "")[:400],
        }

    def _call_candidate_model(self, prompt_path, packet):
        return self.model_call(
            prompt_path,
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=700,
            think=False,
            model_name="gemma3:12b",
            json_schema=CURIOSITY_KNOWLEDGE_CANDIDATE_SCHEMA,
        )

    @staticmethod
    def _normalize_candidate(raw, packet):
        if not isinstance(raw, dict) or raw.get("decision") != "VERIFY":
            return {
                "decision": "SKIP",
                "reason": str((raw or {}).get("reason") or "model_skip")[:300],
            }
        claim = " ".join(str(raw.get("claim") or "").split())[:1200]
        subject = " ".join(str(raw.get("subject") or "").split())[:200]
        risk = str(raw.get("risk") or "high").lower()
        knowledge_type = str(raw.get("knowledge_type") or "event").lower()
        if (
            not claim
            or not subject
            or risk != "low"
            or knowledge_type not in {"stable", "changing"}
        ):
            return {"decision": "SKIP", "reason": "candidate_policy_gate"}

        # Explanatory biology/physics/mechanism questions describe durable
        # knowledge unless the question itself contains an explicit time cue.
        question = str(packet.get("question") or "")
        if (
            _CAUSAL_QUESTION_RE.search(question)
            and not _TEMPORAL_QUESTION_RE.search(question)
        ):
            knowledge_type = "stable"

        result = deepcopy(raw)
        result["claim"] = claim
        result["subject"] = subject
        result["risk"] = risk
        result["knowledge_type"] = knowledge_type
        result["valid_for_days"] = (
            None if knowledge_type == "stable" else result.get("valid_for_days")
        )
        if knowledge_type == "changing" and not isinstance(
            result.get("valid_for_days"), int
        ):
            return {"decision": "SKIP", "reason": "changing_claim_missing_expiry"}
        result["reason"] = (
            "从外部回答中提取的核心候选事实，需要独立验证。"
            if _CJK_RE.search(question)
            else "Core candidate fact extracted from the external answer for independent verification."
        )
        return result

    @staticmethod
    def _direct_answer_gate(question, claim):
        """Reject incidental facts when the curiosity asks for an explanation."""
        question = " ".join(str(question or "").split())
        claim = " ".join(str(claim or "").split())
        if _CAUSAL_QUESTION_RE.search(question) and not _CAUSAL_CLAIM_RE.search(claim):
            return False, "causal_answer_required"
        return True, "direct_answer"

    def prepare_candidate(self, item):
        """Extract one public factual hypothesis; this does not verify it."""
        packet = self._item_packet(item)
        if not packet["curiosity_id"] or not packet["external_ai_answer"]:
            return {"decision": "SKIP", "reason": "missing_external_answer"}
        try:
            raw = self._call_candidate_model(
                "prompts/nerv_curiosity_knowledge_candidate.txt",
                packet,
            )
            result = self._normalize_candidate(raw, packet)
            if result.get("decision") == "VERIFY":
                allowed, reason = self._direct_answer_gate(
                    packet["question"], result.get("claim")
                )
                if not allowed:
                    print("[NERV KNOWLEDGE CANDIDATE RECOVERY]", reason)
                    recovery_packet = dict(packet)
                    recovery_packet["rejected_candidate"] = {
                        "subject": result.get("subject"),
                        "claim": result.get("claim"),
                        "rejection_reason": reason,
                    }
                    raw = self._call_candidate_model(
                        "prompts/nerv_curiosity_knowledge_candidate_recovery.txt",
                        recovery_packet,
                    )
                    result = self._normalize_candidate(raw, packet)
        finally:
            self._release("CANDIDATE")
        if result.get("decision") == "VERIFY":
            allowed, reason = self._direct_answer_gate(
                packet["question"], result.get("claim")
            )
            if not allowed:
                return {"decision": "SKIP", "reason": reason}
        return result

    @staticmethod
    def build_query(claim, fallback_builder):
        """Preserve non-English entities instead of asking AI to translate them."""
        compact_claim = " ".join(str(claim or "").split()).strip()[:180]
        if not compact_claim:
            return ""
        if _CJK_RE.search(compact_claim):
            query = compact_claim + " scientific study official research"
            print("[NERV ENTITY-ANCHORED QUERY]", repr(query))
            return query
        return fallback_builder(compact_claim)

    @staticmethod
    def evidence_gate(search_result):
        """Require readable, independent web evidence before semantic review."""
        result = search_result if isinstance(search_result, dict) else {}
        judgment = result.get("judgment") if isinstance(result.get("judgment"), dict) else {}
        sources = []
        domains = set()
        for item in result.get("results", []):
            if not isinstance(item, dict) or item.get("page_success") is not True:
                continue
            try:
                score = int(item.get("source_score", 0))
            except (TypeError, ValueError):
                score = 0
            domain = str(item.get("domain") or "").lower().removeprefix("www.")
            url = str(item.get("url") or "").strip()
            if score < MIN_SOURCE_SCORE or not domain or not url or domain in domains:
                continue
            domains.add(domain)
            sources.append({
                "title": str(item.get("title") or "")[:300],
                "domain": domain,
                "url": url[:2000],
                "source_score": score,
            })
        try:
            votes = int(judgment.get("votes") or 0)
        except (TypeError, ValueError):
            votes = 0
        allowed = (
            str(result.get("status") or "").upper() == "OK"
            and judgment.get("consensus") is True
            and judgment.get("need_more_sources") is not True
            and votes >= MIN_CONSENSUS_VOTES
            and len(sources) >= MIN_INDEPENDENT_SOURCES
        )
        return {
            "allowed": allowed,
            "sources": sources,
            "votes": votes,
            "reason": (
                "independent_consensus"
                if allowed
                else "insufficient_independent_evidence"
            ),
        }

    def evaluate(self, item, candidate, search_result):
        """Compare the hypothesis with search evidence after the hard gate."""
        gate = self.evidence_gate(search_result)
        if not gate["allowed"]:
            return {
                "decision": "KEEP_UNVERIFIED",
                "reason": gate["reason"],
                "evidence_gate": gate,
            }
        result = search_result if isinstance(search_result, dict) else {}
        item_packet = self._item_packet(item)
        candidate_packet = {
            key: candidate.get(key)
            for key in (
                "subject", "claim", "topics", "knowledge_type",
                "valid_for_days", "risk",
            )
        }
        judgment = result.get("judgment")
        judgment = judgment if isinstance(judgment, dict) else {}
        judgment_packet = {
            key: judgment.get(key)
            for key in (
                "consensus", "canonical_answer", "votes", "need_more_sources",
            )
        }
        packet = {
            "curiosity": {
                "curiosity_id": item_packet["curiosity_id"],
                "question": item_packet["question"],
                "external_ai_status": "UNVERIFIED_EXTERNAL_AI",
            },
            "candidate_hypothesis": candidate_packet,
            "search_status": result.get("status"),
            "evidence_judgment": judgment_packet,
            "extracted_evidence": result.get("answers", [])[:7],
            "qualified_sources": gate["sources"],
            "rules": [
                "External AI is hypothesis only and is never evidence.",
                "The original question and candidate claim are authoritative for entity identity.",
                "Free-form candidate/search reasons are intentionally excluded.",
            ],
        }
        try:
            raw = self.model_call(
                "prompts/nerv_curiosity_knowledge_verdict.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=8192,
                num_predict=850,
                think=False,
                model_name="gemma3:12b",
                json_schema=CURIOSITY_KNOWLEDGE_VERDICT_SCHEMA,
            )
        finally:
            self._release("VERDICT")
        if not isinstance(raw, dict):
            return {
                "decision": "KEEP_UNVERIFIED",
                "reason": "invalid_verdict",
                "evidence_gate": gate,
            }
        verdict = deepcopy(raw)
        verdict["evidence_gate"] = gate
        if verdict.get("decision") != "PROMOTE":
            return verdict
        try:
            confidence = float(verdict.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if (
            str(verdict.get("risk") or "high").lower() != "low"
            or str(verdict.get("knowledge_type") or "event").lower()
            not in {"stable", "changing"}
            or confidence < 0.85
            or not str(verdict.get("canonical_claim") or "").strip()
        ):
            verdict["decision"] = "KEEP_UNVERIFIED"
            verdict["reason"] = "verdict_policy_gate"
        return verdict
