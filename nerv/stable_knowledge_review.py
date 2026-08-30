"""Bounded random rechecks for already-verified stable Knowledge."""

from datetime import datetime
import json

import knowledge


STABLE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": [
                "SUPPORTED",
                "CONTRADICTED",
                "INSUFFICIENT_EVIDENCE",
            ],
        },
        "exact_claim_checked": {"type": "boolean"},
        "no_silent_replacement": {"type": "boolean"},
        "reason": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": [
        "decision",
        "exact_claim_checked",
        "no_silent_replacement",
        "reason",
    ],
    "additionalProperties": False,
}


class StableKnowledgeReviewer:
    """Recheck at most one randomly sampled stable record per idle day."""

    def __init__(self, model_call, unload_model=None):
        self.model_call = model_call
        self.unload_model = unload_model

    @staticmethod
    def _local_date():
        return datetime.now().astimezone().date().isoformat()

    def due(self):
        return knowledge.stable_review_due(local_date=self._local_date())

    def _release(self):
        if self.unload_model is None:
            return
        try:
            self.unload_model("gemma4:12b")
            print("[NERV STABLE REVIEW MODEL RELEASED] gemma4:12b")
        except Exception as error:
            print("[NERV STABLE REVIEW RELEASE WARNING]", repr(error))

    @staticmethod
    def _qualified_sources(search_result):
        result = search_result if isinstance(search_result, dict) else {}
        sources = []
        domains = set()
        for item in result.get("results", [])[:10]:
            if not isinstance(item, dict) or item.get("page_success") is not True:
                continue
            try:
                score = int(item.get("source_score") or 0)
            except (TypeError, ValueError):
                score = 0
            domain = str(item.get("domain") or "").lower().removeprefix("www.")
            if score < 70 or not domain or domain in domains:
                continue
            domains.add(domain)
            sources.append({
                "title": str(item.get("title") or "")[:300],
                "domain": domain[:200],
                "url": str(item.get("url") or "")[:2000],
                "source_score": score,
            })
        return sources

    def _judge(self, item, search_result, sources):
        answers = [
            {
                "index": value.get("index"),
                "answer": str(value.get("answer") or "")[:1600],
            }
            for value in (search_result or {}).get("answers", [])[:7]
            if isinstance(value, dict) and str(value.get("answer") or "").strip()
        ]
        if not sources or not answers:
            return {
                "decision": "INSUFFICIENT_EVIDENCE",
                "reason": "No qualified readable evidence directly addressed the stored claim.",
            }
        packet = {
            "stored_knowledge": {
                "knowledge_id": str(item.get("id") or "")[:160],
                "subject": str(item.get("subject") or "")[:300],
                "exact_claim": str(item.get("claim") or "")[:3000],
                "knowledge_type": "stable",
            },
            "bounded_3_5_7_search": {
                "status": str((search_result or {}).get("status") or "")[:80],
                "query": str((search_result or {}).get("query") or "")[:700],
                "judgment": (
                    search_result.get("judgment")
                    if isinstance(search_result.get("judgment"), dict)
                    else {}
                ),
                "answers": answers,
                "qualified_sources": sources,
            },
        }
        try:
            raw = self.model_call(
                "prompts/nerv_stable_knowledge_review.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=8192,
                num_predict=420,
                think=False,
                model_name="gemma4:12b",
                json_schema=STABLE_REVIEW_SCHEMA,
            )
        finally:
            self._release()
        if (
            not isinstance(raw, dict)
            or raw.get("exact_claim_checked") is not True
            or raw.get("no_silent_replacement") is not True
            or str(raw.get("decision") or "").upper() not in {
                "SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE",
            }
            or not str(raw.get("reason") or "").strip()
        ):
            return {
                "decision": "FAILED",
                "reason": "invalid_stable_review_verdict",
            }
        decision = str(raw["decision"]).upper()
        judgment = search_result.get("judgment")
        judgment = judgment if isinstance(judgment, dict) else {}
        try:
            votes = int(judgment.get("votes") or 0)
        except (TypeError, ValueError):
            votes = 0
        # Quarantining a claim requires strong independent contradiction.
        # Insufficient evidence never changes the active claim.
        if decision == "CONTRADICTED" and not (
            str(search_result.get("status") or "").upper() == "OK"
            and judgment.get("consensus") is True
            and votes >= 2
            and len(sources) >= 2
        ):
            decision = "INSUFFICIENT_EVIDENCE"
        return {
            "decision": decision,
            "reason": str(raw.get("reason") or "")[:500],
        }

    def run_once(self, force=False, rng=None):
        local_date = self._local_date()
        if not force and not self.due():
            return {"status": "SKIPPED", "reason": "not_due"}
        item = knowledge.select_stable_review_candidate(rng=rng)
        if not isinstance(item, dict):
            knowledge.record_stable_review_run(
                "SKIPPED",
                details={"reason": "no_eligible_stable_knowledge"},
                local_date=local_date,
            )
            return {"status": "SKIPPED", "reason": "empty"}
        knowledge_id = str(item.get("id") or "")
        try:
            import tools

            query = tools.build_claim_query(str(item.get("claim") or ""))
            search_result = tools.search_controller(
                query,
                status_callback=None,
                evidence_budgets=(3, 5, 7),
            )
            sources = self._qualified_sources(search_result)
            verdict = self._judge(item, search_result, sources)
            decision = str(verdict.get("decision") or "FAILED").upper()
            updated = knowledge.record_stable_review_result(
                knowledge_id,
                decision,
                verdict.get("reason") or "",
                sources,
            )
            if updated is None:
                decision = "FAILED"
                verdict["reason"] = "knowledge_record_not_reviewable"
            knowledge.record_stable_review_run(
                decision,
                knowledge_id=knowledge_id,
                details={
                    "reason": str(verdict.get("reason") or "")[:500],
                    "source_count": len(sources),
                    "priority": item.get("stable_review_priority"),
                    "claim_replaced": False,
                },
                local_date=local_date,
            )
            print(
                "[NERV STABLE KNOWLEDGE REVIEW]",
                "status=" + decision,
                "knowledge_id=" + knowledge_id,
                "sources=" + str(len(sources)),
            )
            return {
                "status": decision,
                "knowledge_id": knowledge_id,
                "source_count": len(sources),
            }
        except Exception as error:
            knowledge.record_stable_review_result(
                knowledge_id,
                "FAILED",
                type(error).__name__ + ": " + str(error)[:400],
                [],
            )
            knowledge.record_stable_review_run(
                "FAILED",
                knowledge_id=knowledge_id,
                details={
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                    "claim_replaced": False,
                },
                local_date=local_date,
            )
            print("[NERV STABLE KNOWLEDGE REVIEW WARNING]", repr(error))
            return {
                "status": "FAILED",
                "knowledge_id": knowledge_id,
                "error": type(error).__name__,
            }
