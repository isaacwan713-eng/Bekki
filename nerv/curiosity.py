"""Observable, privacy-bounded self-initiated curiosity for NERV."""

import hashlib
import json
import re
import threading
from copy import deepcopy
from datetime import datetime

from . import governance
from .schemas import (
    CURIOSITY_SCHEMA_VERSION,
    CURIOSITY_SELECTION_SCHEMA,
    CURIOSITY_WRITER_SCHEMA,
)


_LOCK = threading.RLock()
MAX_ITEMS = 100
MAX_DRAFTS_FOR_SELECTION = 20
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


class CuriosityJournal:
    def __init__(self, model_call, unload_model=None, base_dir=None):
        self.model_call = model_call
        self.unload_model = unload_model
        self.directory = governance.data_directory(base_dir)
        self.path = self.directory / "curiosity.json"
        self.audit_path = self.directory / "curiosity_audit.jsonl"
        self._ensure()

    @staticmethod
    def _default():
        return {
            "schema_version": CURIOSITY_SCHEMA_VERSION,
            "revision": 0,
            "enabled": True,
            "daily_limit": 3,
            "items": [],
        }

    def _ensure(self):
        if not self.path.exists():
            governance.save_json(self.path, self._default())

    def load(self):
        value = governance.load_json(self.path, self._default())
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return self._default()
        value.setdefault("schema_version", CURIOSITY_SCHEMA_VERSION)
        value.setdefault("revision", 0)
        value.setdefault("enabled", True)
        value.setdefault("daily_limit", 3)
        return value

    @staticmethod
    def _safe_number(value):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _id(question, created_at):
        material = (str(question) + "\0" + str(created_at)).encode("utf-8")
        return "curiosity_" + hashlib.sha256(material).hexdigest()[:20]

    @staticmethod
    def _local_date(iso_value):
        value = str(iso_value or "").strip()
        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.astimezone()
            return parsed.astimezone().date().isoformat()
        except ValueError:
            return ""

    def observe_turn(self, user_message, assistant_reply, response_mode):
        """Let AI propose one privacy-safe curiosity; Python checks contract."""
        message = str(user_message or "").strip()
        if not message:
            return {"status": "ignored", "reason": "empty_message"}
        packet = {
            "completed_turn": {
                "user_message": message[:2400],
                "bekki_reply": str(assistant_reply or "")[:2400],
                "response_mode": str(response_mode or "")[:80],
            },
            "existing_draft_questions": [
                str(item.get("question") or "")[:500]
                for item in self.load().get("items", [])
                if isinstance(item, dict) and item.get("state") == "DRAFT"
            ][-20:],
        }
        try:
            raw = self.model_call(
                "prompts/nerv_curiosity_writer.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=6144,
                num_predict=700,
                think=False,
                model_name="gemma3:12b",
                json_schema=CURIOSITY_WRITER_SCHEMA,
            )
        finally:
            self._release("gemma3:12b", "WRITER")
        proposal = raw.get("proposal") if isinstance(raw, dict) else None
        if not isinstance(proposal, dict):
            return {"status": "ignored", "reason": "no_curiosity"}
        question = governance.compact_text(proposal.get("question"), 800)
        reason = governance.compact_text(proposal.get("reason"), 600)
        trigger = governance.compact_text(proposal.get("trigger_summary"), 400)
        risk = str(proposal.get("sharing_risk") or "PROHIBITED").upper()
        interest = self._safe_number(proposal.get("interest_score"))
        confidence = self._safe_number(proposal.get("confidence"))
        message_is_cjk = bool(_CJK_RE.search(message))
        # Only ``question`` leaves Bekki for ChatGPT, so its language remains a
        # hard boundary.  ``reason`` and ``trigger_summary`` are local journal
        # metadata. Small local models sometimes emit them in English or even
        # introduce a wrong English noun while the outbound Chinese question
        # is correct. Replace a mismatched visible reason with a bounded local
        # explanation instead of discarding the useful question. The trigger
        # remains internal and does not participate in the language gate.
        language_matches = not message_is_cjk or bool(_CJK_RE.search(question))
        if message_is_cjk and reason and not _CJK_RE.search(reason):
            reason = "这个问题来自刚才的对话，值得进一步了解。"
        if (
            not question
            or not reason
            or not trigger
            or risk != "NORMAL"
            or interest < 0.65
            or confidence < 0.85
            or not language_matches
        ):
            governance.append_jsonl(
                self.audit_path,
                {
                    "event": "curiosity_proposal_rejected",
                    "sharing_risk": risk,
                    "interest_score": interest,
                    "confidence": confidence,
                    "language_matches": language_matches,
                },
            )
            return {"status": "dismissed", "reason": "privacy_or_quality_gate"}

        state = self.load()
        normalized = question.casefold()
        if any(
            str(item.get("question") or "").casefold() == normalized
            and item.get("state") in {"DRAFT", "ASKED", "ANSWERED_UNVERIFIED"}
            for item in state["items"]
            if isinstance(item, dict)
        ):
            return {"status": "ignored", "reason": "duplicate"}
        now = governance.now_iso()
        record = {
            "id": self._id(question, now),
            "state": "DRAFT",
            "question": question,
            "reason": reason,
            "trigger_summary": trigger,
            "interest_score": interest,
            "confidence": confidence,
            "sharing_risk": "NORMAL",
            "created_at": now,
            "source": "nerv_ai_curiosity",
        }
        with _LOCK:
            state = self.load()
            state["items"].append(record)
            state["items"] = state["items"][-MAX_ITEMS:]
            state["revision"] = int(state.get("revision", 0)) + 1
            governance.save_json(self.path, state)
        governance.append_jsonl(
            self.audit_path,
            {"event": "curiosity_drafted", "id": record["id"]},
        )
        return {"status": "drafted", "id": record["id"]}

    def _release(self, model_name, stage):
        if self.unload_model is None:
            return
        try:
            self.unload_model(model_name)
            print("[NERV CURIOSITY MODEL RELEASED]", stage, model_name)
        except Exception as error:
            print("[NERV CURIOSITY MODEL RELEASE WARNING]", stage, repr(error))

    def due(self):
        state = self.load()
        if state.get("enabled") is not True:
            return False
        today = datetime.now().astimezone().date().isoformat()
        try:
            limit = max(0, min(3, int(state.get("daily_limit", 3))))
        except (TypeError, ValueError):
            limit = 3
        used_today = sum(
            1
            for item in state.get("items", [])
            if isinstance(item, dict)
            and (
                self._local_date(item.get("asked_at")) == today
                or self._local_date(item.get("last_attempt_at")) == today
            )
        )
        has_draft = any(
            isinstance(item, dict)
            and item.get("state") == "DRAFT"
            and self._local_date(item.get("last_attempt_at")) != today
            for item in state.get("items", [])
        )
        return limit > used_today and has_draft

    def select_daily_question(self):
        if not self.due():
            return None
        drafts = [
            deepcopy(item)
            for item in self.load().get("items", [])
            if isinstance(item, dict)
            and item.get("state") == "DRAFT"
            and self._local_date(item.get("last_attempt_at"))
            != datetime.now().astimezone().date().isoformat()
        ][-MAX_DRAFTS_FOR_SELECTION:]
        catalog = [
            {
                "id": item.get("id"),
                "question": item.get("question"),
                "reason": item.get("reason"),
                "trigger_summary": item.get("trigger_summary"),
                "interest_score": item.get("interest_score"),
                "created_at": item.get("created_at"),
            }
            for item in drafts
        ]
        try:
            raw = self.model_call(
                "prompts/nerv_curiosity_select.txt",
                json.dumps(
                    {"current_date": datetime.now().date().isoformat(), "drafts": catalog},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=4096,
                num_predict=350,
                think=False,
                model_name="gemma3:12b",
                json_schema=CURIOSITY_SELECTION_SCHEMA,
            )
        finally:
            self._release("gemma3:12b", "SELECT")
        if not isinstance(raw, dict) or raw.get("decision") != "ASK":
            return None
        selected_id = str(raw.get("candidate_id") or "")
        return next((item for item in drafts if item.get("id") == selected_id), None)

    def record_external_result(self, candidate_id, result):
        result = result if isinstance(result, dict) else {}
        with _LOCK:
            state = self.load()
            item = next(
                (
                    value for value in state["items"]
                    if isinstance(value, dict) and value.get("id") == candidate_id
                ),
                None,
            )
            if item is None or item.get("state") != "DRAFT":
                return {"status": "ignored", "reason": "candidate_unavailable"}
            status = str(result.get("status") or "failed").upper()
            if status == "COMPLETED":
                item["state"] = "ANSWERED_UNVERIFIED"
                item["asked_at"] = governance.now_iso()
                item["outbound_prompt"] = governance.compact_text(
                    result.get("outbound_prompt") or item.get("question"), 1200
                )
                item["answer"] = governance.compact_text(
                    result.get("answer"), 6000
                )
                item["answered_at"] = governance.now_iso()
            else:
                item["last_attempt_status"] = status
                item["last_attempt_at"] = governance.now_iso()
            state["revision"] = int(state.get("revision", 0)) + 1
            governance.save_json(self.path, state)
        return {"status": item.get("state"), "id": candidate_id}

    def get_item(self, candidate_id):
        """Return one journal item by exact opaque ID."""
        wanted = str(candidate_id or "")
        if not wanted:
            return None
        return next(
            (
                deepcopy(item)
                for item in self.load().get("items", [])
                if isinstance(item, dict) and item.get("id") == wanted
            ),
            None,
        )

    def record_verification_outcome(
        self,
        candidate_id,
        status,
        reason,
        claim="",
        sources=None,
        knowledge_id=None,
    ):
        """Record the independent check without treating External AI as proof."""
        allowed = {
            "VERIFIED",
            "SKIPPED",
            "INSUFFICIENT_EVIDENCE",
            "REJECTED",
            "FAILED",
        }
        normalized = str(status or "FAILED").upper()
        if normalized not in allowed:
            normalized = "FAILED"
        clean_sources = []
        for source in sources or []:
            if not isinstance(source, dict):
                continue
            domain = str(source.get("domain") or "")[:300]
            url = str(source.get("url") or "")[:2000]
            if domain and url:
                clean_sources.append({
                    "title": str(source.get("title") or "")[:300],
                    "domain": domain,
                    "url": url,
                })
            if len(clean_sources) >= 5:
                break
        with _LOCK:
            state = self.load()
            item = next(
                (
                    value for value in state["items"]
                    if isinstance(value, dict) and value.get("id") == candidate_id
                ),
                None,
            )
            if item is None or item.get("state") not in {
                "ANSWERED_UNVERIFIED", "VERIFIED"
            }:
                return {"status": "ignored", "reason": "candidate_unavailable"}
            item["verification"] = {
                "status": normalized,
                "claim": governance.compact_text(claim, 3000),
                "reason": governance.compact_text(reason, 800),
                "sources": clean_sources,
                "knowledge_id": str(knowledge_id or "")[:160] or None,
                "checked_at": governance.now_iso(),
                "external_ai_role": "hypothesis_only",
            }
            if normalized == "VERIFIED":
                item["state"] = "VERIFIED"
                item["verified_at"] = governance.now_iso()
            state["revision"] = int(state.get("revision", 0)) + 1
            governance.save_json(self.path, state)
        return {"status": item.get("state"), "id": candidate_id}

    def journal_reply(self, language="zh-CN"):
        items = [
            item for item in self.load().get("items", [])
            if isinstance(item, dict)
            and item.get("state") in {"DRAFT", "ANSWERED_UNVERIFIED", "VERIFIED"}
        ]
        items.sort(
            key=lambda item: str(item.get("answered_at") or item.get("created_at") or ""),
            reverse=True,
        )
        if not items:
            if str(language).lower().startswith("zh"):
                return "今天还没有形成值得记录的好奇问题。", 0
            return "I have not formed a curiosity worth recording today.", 0
        lines = ["Bekki 最近的好奇心："]
        for index, item in enumerate(items[:8], start=1):
            state = item.get("state")
            label = {
                "DRAFT": "还在想",
                "ANSWERED_UNVERIFIED": "已问 ChatGPT，尚未验证",
                "VERIFIED": "已验证",
            }.get(state, state)
            lines.append(str(index) + ". " + str(item.get("question") or ""))
            lines.append("   原因：" + str(item.get("reason") or ""))
            lines.append("   状态：" + str(label))
            if state == "DRAFT" and item.get("last_attempt_status"):
                attempt_label = {
                    "LOGIN_REQUIRED": "专用 ChatGPT 浏览器等待你登录",
                    "HUMAN_VERIFICATION_REQUIRED": "等待你完成人机验证",
                    "RESPONSE_TIMEOUT": "页面回答等待超时",
                }.get(
                    str(item.get("last_attempt_status") or "").upper(),
                    "上次询问没有完成",
                )
                lines.append("   上次尝试：" + attempt_label)
            if item.get("answer"):
                lines.append("   ChatGPT：" + str(item.get("answer"))[:800])
            verification = item.get("verification")
            if isinstance(verification, dict):
                verification_status = str(
                    verification.get("status") or ""
                ).upper()
                verification_label = {
                    "VERIFIED": "已通过独立搜索验证并进入 Knowledge",
                    "SKIPPED": "不适合进入长期 Knowledge",
                    "INSUFFICIENT_EVIDENCE": "独立证据不足，仍未验证",
                    "REJECTED": "独立证据不支持，未进入 Knowledge",
                    "FAILED": "核验没有完成",
                }.get(verification_status, verification_status)
                if verification_label:
                    lines.append("   核验：" + verification_label)
                verified_claim = str(verification.get("claim") or "").strip()
                if verified_claim:
                    lines.append("   验证后的知识：" + verified_claim[:1000])
                source_domains = [
                    str(source.get("domain") or "")
                    for source in verification.get("sources", [])
                    if isinstance(source, dict) and source.get("domain")
                ]
                if source_domains:
                    lines.append("   独立来源：" + "、".join(source_domains[:5]))
        return "\n".join(lines), len(items)
