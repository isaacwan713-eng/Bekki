"""Turn an external-AI curiosity answer into an independently checked candidate."""

import json
import re
from copy import deepcopy
from datetime import datetime

from .schemas import (
    CURIOSITY_KNOWLEDGE_CANDIDATE_SCHEMA,
    CURIOSITY_KNOWLEDGE_CERTIFICATION_SCHEMA,
    CURIOSITY_KNOWLEDGE_VERDICT_SCHEMA,
    KNOWLEDGE_DOMAINS,
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
_PERSISTABLE_LIFECYCLE_SHAPES = {
    "FIXED_HISTORY": "stable",
    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM": "stable",
    "MAINTAINED_SET_OR_STRUCTURE": "reviewable",
}
_TRANSIENT_LIFECYCLE_BASIS = "TRANSIENT_NONSTRUCTURAL_STATE_OR_EVENT"


class CuriosityKnowledgeVerifier:
    """AI proposes semantics; Python owns the evidence and persistence gates."""

    def __init__(self, model_call, unload_model=None):
        self.model_call = model_call
        self.unload_model = unload_model

    def _release(self, stage):
        if self.unload_model is None:
            return
        try:
            self.unload_model("gemma4:12b")
            print("[NERV KNOWLEDGE MODEL RELEASED]", stage, "gemma4:12b")
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
            "authoritative_current_date": (
                datetime.now().astimezone().date().isoformat()
            ),
            "current_date_role": "HOST_LOCAL_TEMPORAL_AUTHORITY",
        }

    def _call_candidate_model(self, prompt_path, packet):
        return self.model_call(
            prompt_path,
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=700,
            think=False,
            model_name="gemma4:12b",
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
        knowledge_domain = str(
            raw.get("knowledge_domain") or "other"
        ).lower().strip()
        if knowledge_domain not in KNOWLEDGE_DOMAINS:
            knowledge_domain = "other"
        verification_level = str(
            raw.get("verification_level") or "double"
        ).lower().strip()
        if verification_level not in {"standard", "double"}:
            verification_level = "double"
        if knowledge_domain in {"medical", "legal"}:
            verification_level = "double"

        question = str(packet.get("question") or "")
        temporal_scope = raw.get("temporal_scope")
        normalized_temporal_scope = None
        if isinstance(temporal_scope, dict):
            scope_type = str(
                temporal_scope.get("scope_type") or ""
            ).upper()
            requested_period = " ".join(
                str(temporal_scope.get("requested_period") or "").split()
            )[:240]
            if scope_type in {
                "LATEST_COMPLETED_PERIOD", "EXPLICIT_PERIOD"
            } and requested_period:
                normalized_temporal_scope = {
                    "scope_type": scope_type,
                    "requested_period": requested_period,
                    "allow_previous_period": False,
                }
        lifecycle_basis = str(
            raw.get("lifecycle_basis") or ""
        ).upper().strip()
        if not lifecycle_basis:
            if knowledge_type == "stable" and normalized_temporal_scope:
                lifecycle_basis = "FIXED_HISTORY"
            elif knowledge_type == "stable":
                lifecycle_basis = (
                    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                )
            elif knowledge_type == "reviewable":
                lifecycle_basis = "MAINTAINED_SET_OR_STRUCTURE"
            else:
                lifecycle_basis = _TRANSIENT_LIFECYCLE_BASIS

        # Explanatory biology/physics/mechanism questions describe durable
        # knowledge unless the question itself contains an explicit time cue.
        causal_lifecycle_override = (
            _CAUSAL_QUESTION_RE.search(question)
            and not _TEMPORAL_QUESTION_RE.search(question)
        )
        if causal_lifecycle_override:
            knowledge_type = "stable"
            lifecycle_basis = (
                "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
            )
            normalized_temporal_scope = None
        if (
            not claim
            or not subject
            or risk != "low"
        ):
            return {
                "decision": "SKIP",
                "reason": "candidate_policy_gate",
            }

        if lifecycle_basis == _TRANSIENT_LIFECYCLE_BASIS or knowledge_type in {
            "changing", "event", "news"
        }:
            return {
                "decision": "SKIP",
                "reason": "non_reusable_knowledge",
            }

        expected_type = _PERSISTABLE_LIFECYCLE_SHAPES.get(lifecycle_basis)
        valid_for_days = raw.get("valid_for_days")
        lifecycle_valid = expected_type == knowledge_type
        if lifecycle_basis == "FIXED_HISTORY":
            lifecycle_valid = (
                lifecycle_valid
                and normalized_temporal_scope is not None
            )
            valid_for_days = None
        elif lifecycle_basis == (
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
        ):
            lifecycle_valid = lifecycle_valid and (
                valid_for_days is None or causal_lifecycle_override
            )
            valid_for_days = None
        elif lifecycle_basis == "MAINTAINED_SET_OR_STRUCTURE":
            lifecycle_valid = (
                lifecycle_valid
                and isinstance(valid_for_days, int)
                and 1 <= valid_for_days <= 3650
            )
        else:
            lifecycle_valid = False
        if not lifecycle_valid:
            return {
                "decision": "SKIP",
                "reason": "lifecycle_contract_invalid",
            }

        result = deepcopy(raw)
        result["claim"] = claim
        result["subject"] = subject
        result["risk"] = risk
        result["knowledge_type"] = knowledge_type
        result["lifecycle_basis"] = lifecycle_basis
        result["valid_for_days"] = valid_for_days
        result["knowledge_domain"] = knowledge_domain
        result["verification_level"] = verification_level
        result["cluster_label"] = (
            " ".join(str(raw.get("cluster_label") or subject).split())[:120]
        )
        result["temporal_scope"] = normalized_temporal_scope
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
            recovery_reason = ""
            if result.get("decision") == "VERIFY":
                allowed, reason = self._direct_answer_gate(
                    packet["question"], result.get("claim")
                )
                if not allowed:
                    recovery_reason = reason
            elif result.get("reason") == "lifecycle_contract_invalid":
                recovery_reason = "lifecycle_contract_invalid"
            if recovery_reason:
                print(
                    "[NERV KNOWLEDGE CANDIDATE RECOVERY]",
                    recovery_reason,
                )
                recovery_packet = dict(packet)
                recovery_packet["rejected_candidate"] = {
                    "subject": result.get("subject"),
                    "claim": result.get("claim"),
                    "rejection_reason": recovery_reason,
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
    def build_query(
        claim,
        fallback_builder,
        verification_level="double",
        knowledge_domain="other",
    ):
        """Preserve non-English entities instead of asking AI to translate them."""
        compact_claim = " ".join(str(claim or "").split()).strip()[:180]
        if not compact_claim:
            return ""
        if _CJK_RE.search(compact_claim):
            level = str(verification_level or "double").lower().strip()
            domain = str(knowledge_domain or "other").lower().strip()
            if level == "standard":
                query = compact_claim + " 官方资料 可靠来源"
            elif domain == "legal":
                query = compact_claim + " official law primary source"
            elif domain == "medical":
                query = compact_claim + " medical guideline peer reviewed research"
            else:
                query = compact_claim + " scientific study official research"
            print("[NERV ENTITY-ANCHORED QUERY]", repr(query))
            return query
        return fallback_builder(compact_claim)

    @staticmethod
    def evidence_gate(search_result, verification_level="double"):
        """Apply the selected standard or double evidence contract."""
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
        level = str(verification_level or "double").lower().strip()
        if level not in {"standard", "double"}:
            level = "double"
        extracted_answer = any(
            isinstance(item, dict)
            and str(item.get("answer") or "").strip()
            for item in result.get("answers", [])
        )
        if level == "standard":
            allowed = (
                str(result.get("status") or "").upper()
                in {"OK", "INSUFFICIENT_EVIDENCE"}
                and len(sources) >= 1
                and extracted_answer
            )
            success_reason = "ai_plus_source_corroboration"
        else:
            allowed = (
                str(result.get("status") or "").upper() == "OK"
                and judgment.get("consensus") is True
                and judgment.get("need_more_sources") is not True
                and votes >= MIN_CONSENSUS_VOTES
                and len(sources) >= MIN_INDEPENDENT_SOURCES
            )
            success_reason = "double_independent_consensus"
        return {
            "allowed": allowed,
            "sources": sources,
            "votes": votes,
            "verification_level": level,
            "external_ai_can_corroborate": level == "standard",
            "reason": (
                success_reason
                if allowed
                else "insufficient_independent_evidence"
            ),
        }

    def evaluate(self, item, candidate, search_result):
        """Compare the hypothesis with search evidence after the hard gate."""
        verification_level = str(
            candidate.get("verification_level") or "double"
        ).lower().strip()
        if verification_level not in {"standard", "double"}:
            verification_level = "double"
        gate = self.evidence_gate(search_result, verification_level)
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
                "lifecycle_basis", "valid_for_days", "risk", "knowledge_domain",
                "verification_level", "cluster_label",
                "temporal_scope",
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
                "external_ai_supporting_answer": (
                    item_packet["external_ai_answer"]
                    if verification_level == "standard"
                    else None
                ),
            },
            "candidate_hypothesis": candidate_packet,
            "search_status": result.get("status"),
            "evidence_judgment": judgment_packet,
            "extracted_evidence": result.get("answers", [])[:7],
            "qualified_sources": gate["sources"],
            "rules": [
                (
                    "For STANDARD verification, the external AI answer is one corroborating signal and one qualified readable source is still mandatory."
                    if verification_level == "standard"
                    else "For DOUBLE verification, external AI is hypothesis only and never evidence."
                ),
                "The original question and candidate claim are authoritative for entity identity.",
                "Free-form candidate/search reasons are intentionally excluded.",
                "Only stable, reviewable, or fixed-history knowledge may be promoted; current/open state remains journal-only.",
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
                model_name="gemma4:12b",
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
        verdict["verification_level"] = verification_level
        verdict["knowledge_domain"] = str(
            verdict.get("knowledge_domain")
            or candidate.get("knowledge_domain")
            or "other"
        ).lower().strip()
        verdict["cluster_label"] = " ".join(
            str(
                verdict.get("cluster_label")
                or candidate.get("cluster_label")
                or candidate.get("subject")
                or ""
            ).split()
        )[:120]
        if not isinstance(verdict.get("temporal_scope"), dict):
            verdict["temporal_scope"] = candidate.get("temporal_scope")
        verdict["lifecycle_basis"] = str(
            verdict.get("lifecycle_basis")
            or candidate.get("lifecycle_basis")
            or ""
        ).upper().strip()
        if not verdict["lifecycle_basis"]:
            verdict_type = str(
                verdict.get("knowledge_type") or "event"
            ).lower()
            if verdict_type == "stable" and isinstance(
                verdict.get("temporal_scope"), dict
            ):
                verdict["lifecycle_basis"] = "FIXED_HISTORY"
            elif verdict_type == "stable":
                verdict["lifecycle_basis"] = (
                    "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
                )
            elif verdict_type == "reviewable":
                verdict["lifecycle_basis"] = (
                    "MAINTAINED_SET_OR_STRUCTURE"
                )
        if verdict.get("decision") != "PROMOTE":
            return verdict
        try:
            confidence = float(verdict.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence_floor = 0.80 if verification_level == "standard" else 0.88
        knowledge_type = str(
            verdict.get("knowledge_type") or "event"
        ).lower()
        lifecycle_basis = str(
            verdict.get("lifecycle_basis") or ""
        ).upper()
        expected_type = _PERSISTABLE_LIFECYCLE_SHAPES.get(lifecycle_basis)
        valid_for_days = verdict.get("valid_for_days")
        lifecycle_valid = expected_type == knowledge_type
        if lifecycle_basis == "FIXED_HISTORY":
            temporal_scope = verdict.get("temporal_scope")
            lifecycle_valid = (
                lifecycle_valid
                and isinstance(temporal_scope, dict)
                and str(temporal_scope.get("scope_type") or "").upper()
                in {"LATEST_COMPLETED_PERIOD", "EXPLICIT_PERIOD"}
                and bool(str(temporal_scope.get("requested_period") or "").strip())
                and temporal_scope.get("allow_previous_period") is False
                and valid_for_days is None
            )
        elif lifecycle_basis == (
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
        ):
            lifecycle_valid = lifecycle_valid and valid_for_days is None
        elif lifecycle_basis == "MAINTAINED_SET_OR_STRUCTURE":
            lifecycle_valid = (
                lifecycle_valid
                and isinstance(valid_for_days, int)
                and 1 <= valid_for_days <= 3650
            )
        else:
            lifecycle_valid = False
        if (
            str(verdict.get("risk") or "high").lower() != "low"
            or not lifecycle_valid
            or confidence < confidence_floor
            or not str(verdict.get("canonical_claim") or "").strip()
        ):
            verdict["decision"] = "KEEP_UNVERIFIED"
            verdict["reason"] = "verdict_policy_gate"
            return verdict
        if verification_level == "double":
            certification_packet = {
                "question": item_packet["question"],
                "candidate_hypothesis": candidate_packet,
                "first_verdict": {
                    key: verdict.get(key)
                    for key in (
                        "subject", "canonical_claim", "topics",
                        "knowledge_domain", "cluster_label", "knowledge_type",
                        "lifecycle_basis", "valid_for_days", "temporal_scope",
                        "confidence",
                    )
                },
                "extracted_evidence": result.get("answers", [])[:7],
                "qualified_sources": gate["sources"],
            }
            try:
                certification = self.model_call(
                    "prompts/nerv_curiosity_knowledge_double_certify.txt",
                    json.dumps(
                        certification_packet,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    expect_json=True,
                    num_ctx=6144,
                    num_predict=420,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=CURIOSITY_KNOWLEDGE_CERTIFICATION_SCHEMA,
                )
            finally:
                self._release("DOUBLE_CERTIFICATION")
            try:
                certification_confidence = float(
                    (certification or {}).get("confidence") or 0
                )
            except (TypeError, ValueError):
                certification_confidence = 0.0
            if (
                not isinstance(certification, dict)
                or certification.get("decision") != "CERTIFY"
                or certification_confidence < 0.88
            ):
                verdict["decision"] = "KEEP_UNVERIFIED"
                verdict["reason"] = "double_certification_failed"
            else:
                verdict["double_certification"] = {
                    "decision": "CERTIFY",
                    "confidence": certification_confidence,
                    "reason": str(certification.get("reason") or "")[:400],
                }
        return verdict
