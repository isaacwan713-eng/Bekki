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
MIN_HARD_CONFIDENCE = 0.40
DEFAULT_DAILY_LIMIT = 10
MAX_DAILY_LIMIT = 10
DAILY_LIMIT_VERSION = 2
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_QUOTED_LABEL_RE = re.compile(
    r'["“「『]([^"”」』\r\n]{2,12})["”」』]'
)
_IDENTITY_QUESTION_RE = re.compile(
    r"指代哪些(?:人物|人|群体)|指的是谁|具体是谁|是哪两个人|"
    r"who\s+(?:does|do|is|are).{0,24}(?:refer|represent|mean)",
    re.IGNORECASE,
)


def _quoted_labels(value):
    return [
        match.group(1).strip()
        for match in _QUOTED_LABEL_RE.finditer(str(value or ""))
        if match.group(1).strip()
    ]


def _splits_compound_fandom_label(question, user_message):
    """Reject the observed failure mode that treats 卡黄 as two terms."""

    text = str(question or "")
    markers = (
        "这两个词", "两个词分别", "两个字分别", "每个字",
        "分别指代",
    )
    if not any(marker in text for marker in markers):
        return False
    message = str(user_message or "")
    return any(
        len(label) == 2
        and all(_CJK_RE.fullmatch(character) for character in label)
        and label in message
        for label in _quoted_labels(text)
    )


def _reasks_identity_already_grounded(
    question,
    user_message,
    assistant_reply,
    assistant_grounding,
):
    """Reject a nickname identity question only when the reply states it."""

    if assistant_grounding not in {
        "EXTERNAL_EVIDENCE_AVAILABLE", "VERIFIED_KNOWLEDGE",
    }:
        return False
    question = str(question or "")
    if _IDENTITY_QUESTION_RE.search(question) is None:
        return False
    message = str(user_message or "")
    reply = str(assistant_reply or "")
    name_pair = r"[\u3400-\u9fff]{2,4}\s*(?:与|和|、)\s*[\u3400-\u9fff]{2,4}"
    for label in _quoted_labels(question):
        if label not in message and label not in reply:
            continue
        escaped = re.escape(label)
        explicit_patterns = (
            rf"{escaped}[^。！？\r\n]{{0,10}}(?:指代|指的是|即|也就是)"
            rf"[^。！？\r\n]{{0,10}}{name_pair}",
            rf"{escaped}\s*[（(]\s*{name_pair}\s*[）)]",
            rf"{name_pair}\s*[（(]\s*{escaped}\s*[）)]",
        )
        if any(re.search(pattern, reply) for pattern in explicit_patterns):
            return True
    return False


def _compact_writer_recovery_packet(packet):
    """Bound retry context after malformed Writer JSON without changing meaning."""

    packet = packet if isinstance(packet, dict) else {}
    turn = packet.get("completed_turn")
    turn = turn if isinstance(turn, dict) else {}
    history = []
    for item in packet.get("recent_curiosity_history", [])[-6:]:
        if not isinstance(item, dict):
            continue
        history.append(
            {
                "id": str(item.get("id") or "")[:120],
                "question": str(item.get("question") or "")[:240],
                "state": str(item.get("state") or "")[:40],
                "topic_stage": str(item.get("topic_stage") or "")[:40],
                "question_depth": str(item.get("question_depth") or "")[:40],
                "topic_id": str(item.get("topic_id") or "")[:80],
                "foundation_facet": str(
                    item.get("foundation_facet") or ""
                )[:50],
            }
        )
    knowledge = []
    for item in packet.get("active_topic_knowledge", [])[:6]:
        if not isinstance(item, dict):
            continue
        knowledge.append(
            {
                "id": str(item.get("id") or "")[:160],
                "subject": str(item.get("subject") or "")[:180],
                "claim": str(item.get("claim") or "")[:600],
                "facet": str(item.get("facet") or "")[:120],
                "topic_id": str(item.get("topic_id") or "")[:80],
                "knowledge_layer": str(
                    item.get("knowledge_layer") or ""
                )[:40],
                "topic_lifecycle_state": str(
                    item.get("topic_lifecycle_state") or ""
                )[:40],
            }
        )
    return {
        "recovery_reason": "FIRST_WRITER_OUTPUT_WAS_INVALID_OR_TRUNCATED",
        "curiosity_seed": packet.get("curiosity_seed", {}),
        "completed_turn": {
            "user_message": str(turn.get("user_message") or "")[:1200],
            "bekki_reply": str(turn.get("bekki_reply") or "")[:1200],
            "assistant_grounding": str(
                turn.get("assistant_grounding") or ""
            )[:80],
            "response_mode": str(turn.get("response_mode") or "")[:80],
        },
        "existing_draft_questions": [
            str(value)[:240]
            for value in packet.get("existing_draft_questions", [])[-8:]
        ],
        "recent_curiosity_history": history,
        "active_topic_knowledge": knowledge,
    }


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
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "daily_limit_version": DAILY_LIMIT_VERSION,
            "items": [],
        }

    def _ensure(self):
        governance.ensure_json(self.path, self._default())

    def load(self):
        value = governance.load_json(self.path, self._default())
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            return self._default()
        value.setdefault("schema_version", CURIOSITY_SCHEMA_VERSION)
        value.setdefault("revision", 0)
        value.setdefault("enabled", True)
        # V1 stored the hard-coded default of three without distinguishing it
        # from a user preference.  V2 raises Bekki's bounded idle exploration
        # budget to ten, so migrate only that legacy shape.  Future explicit
        # limits remain intact.
        try:
            daily_limit_version = int(
                value.get("daily_limit_version") or 0
            )
        except (TypeError, ValueError):
            daily_limit_version = 0
        if daily_limit_version < DAILY_LIMIT_VERSION:
            value["daily_limit"] = DEFAULT_DAILY_LIMIT
            value["daily_limit_version"] = DAILY_LIMIT_VERSION
            governance.save_json(self.path, value)
        value.setdefault("daily_limit", DEFAULT_DAILY_LIMIT)
        value.setdefault("daily_limit_version", DAILY_LIMIT_VERSION)
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

    def observe_turn(
        self,
        user_message,
        assistant_reply,
        response_mode,
        knowledge_candidates=None,
        seed_kind="USER_TURN",
        seed_metadata=None,
    ):
        """Let AI propose one privacy-safe curiosity; Python checks contract."""
        message = str(user_message or "").strip()
        if not message:
            return {"status": "ignored", "reason": "empty_message"}
        mode = str(response_mode or "")[:80]
        evidence_grounded_modes = {
            "FACT_LOOKUP",
            "CLAIM_CHECK",
            "NEWS_FEED",
            "DISCUSSION_FEED",
            "SOCIAL_RESEARCH",
            "MEDIA_WATCH",
            "SHOPPING_RESEARCH",
            "RECOMMENDATION_RESEARCH",
            "VERIFIED_KNOWLEDGE",
        }
        assistant_grounding = (
            (
                "VERIFIED_KNOWLEDGE"
                if str(seed_kind or "").upper()
                in {
                    "VERIFIED_KNOWLEDGE_IDLE",
                    "TOPIC_GAP",
                    "TOPIC_REFRESH",
                }
                else "EXTERNAL_EVIDENCE_AVAILABLE"
            )
            if mode in evidence_grounded_modes
            else "UNVERIFIED_ASSISTANT_OUTPUT"
        )
        journal_state = self.load()
        # The Writer receives bounded prior question history so the same AI
        # call can judge whether this is a first encounter or a topic Bekki has
        # already explored. Python does not classify topics or choose depth.
        recent_history = [
            {
                "id": str(item.get("id") or "")[:120],
                "question": str(item.get("question") or "")[:500],
                "trigger_summary": str(
                    item.get("trigger_summary") or ""
                )[:300],
                "state": str(item.get("state") or "")[:40],
                "created_at": str(item.get("created_at") or "")[:80],
                "topic_stage": str(
                    item.get("topic_stage") or ""
                )[:40],
                "question_depth": str(
                    item.get("question_depth") or ""
                )[:40],
                "foundation_facet": str(
                    item.get("foundation_facet") or ""
                )[:50],
                "breadth_relation": str(
                    item.get("breadth_relation") or ""
                )[:50],
                "topic_id": str(item.get("topic_id") or "")[:80],
                "topic_lifecycle_state": str(
                    item.get("topic_lifecycle_state") or ""
                )[:40],
            }
            for item in journal_state.get("items", [])
            if isinstance(item, dict)
            and item.get("state") in {
                "DRAFT", "ASKED", "ANSWERED_UNVERIFIED", "VERIFIED",
                "DISMISSED",
            }
            and str(item.get("question") or "").strip()
        ][-20:]
        topic_knowledge = []
        for item in knowledge_candidates or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            curation = item.get("curation")
            curation = curation if isinstance(curation, dict) else {}
            lifecycle = item.get("topic_lifecycle")
            lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
            topic_knowledge.append({
                "id": str(item.get("id") or "")[:160],
                "subject": str(item.get("subject") or "")[:300],
                "claim": str(item.get("claim") or "")[:1400],
                "topics": [
                    str(value)[:80]
                    for value in item.get("topics", [])[:10]
                ],
                "facet": str(curation.get("facet") or "")[:120],
                "topic_id": str(curation.get("topic_id") or "")[:80],
                "knowledge_layer": str(
                    curation.get("knowledge_layer") or ""
                )[:40],
                "topic_lifecycle_state": str(
                    lifecycle.get("state") or ""
                )[:40],
                "topic_completion_score": lifecycle.get("completion_score"),
                "topic_next_focus": str(
                    lifecycle.get("next_focus") or ""
                )[:500],
                "knowledge_type": str(
                    item.get("knowledge_type") or "stable"
                )[:30],
                "temporal_scope": (
                    item.get("temporal_scope")
                    if isinstance(item.get("temporal_scope"), dict)
                    else {}
                ),
            })
            if len(topic_knowledge) >= 10:
                break
        packet = {
            "curiosity_seed": {
                "kind": str(seed_kind or "USER_TURN")[:60],
                "source_curiosity_id": str(
                    (seed_metadata or {}).get("source_curiosity_id")
                    if isinstance(seed_metadata, dict) else ""
                )[:120],
                "source_knowledge_id": str(
                    (seed_metadata or {}).get("source_knowledge_id")
                    if isinstance(seed_metadata, dict) else ""
                )[:160],
                "idle_generation": (
                    str(seed_kind or "").upper()
                    in {
                        "VERIFIED_KNOWLEDGE_IDLE",
                        "TOPIC_GAP",
                        "TOPIC_REFRESH",
                    }
                ),
                "topic_id": str(
                    (seed_metadata or {}).get("topic_id")
                    if isinstance(seed_metadata, dict) else ""
                )[:80],
                "topic_lifecycle_state": str(
                    (seed_metadata or {}).get("topic_lifecycle_state")
                    if isinstance(seed_metadata, dict) else ""
                )[:40],
                "wake_reason": str(
                    (seed_metadata or {}).get("wake_reason")
                    if isinstance(seed_metadata, dict) else ""
                )[:60],
                "next_focus": str(
                    (seed_metadata or {}).get("next_focus")
                    if isinstance(seed_metadata, dict) else ""
                )[:500],
                "interest_score": (
                    (seed_metadata or {}).get("interest_score")
                    if isinstance(seed_metadata, dict) else None
                ),
            },
            "completed_turn": {
                "user_message": message[:2400],
                # A LOCAL answer is not evidence and is intentionally omitted.
                # This prevents Writer from amplifying hallucinated names or
                # lists into the next External AI question.
                "bekki_reply": (
                    str(assistant_reply or "")[:2400]
                    if mode in evidence_grounded_modes
                    else ""
                ),
                "assistant_grounding": assistant_grounding,
                "response_mode": mode,
            },
            "existing_draft_questions": [
                str(item.get("question") or "")[:500]
                for item in journal_state.get("items", [])
                if isinstance(item, dict) and item.get("state") == "DRAFT"
            ][-20:],
            "recent_curiosity_history": recent_history,
            "active_topic_knowledge": topic_knowledge,
        }
        try:
            raw = self.model_call(
                "prompts/nerv_curiosity_writer.txt",
                json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                expect_json=True,
                num_ctx=6144,
                num_predict=1200,
                think=False,
                model_name="gemma4:12b",
                json_schema=CURIOSITY_WRITER_SCHEMA,
            )
            # A real semantic decline is {"proposal": null}. ``None`` means
            # the schema-bound output could not be parsed (commonly because
            # generation ended at its length limit). Retry once with enough
            # room to close the required object instead of misreporting that
            # transport/format failure as "no curiosity".
            if raw is None:
                recovery_packet = _compact_writer_recovery_packet(packet)
                print(
                    "[NERV CURIOSITY WRITER RETRY]",
                    "reason=invalid_or_truncated_json",
                    "mode=compact",
                    "packet_chars=" + str(len(json.dumps(
                        recovery_packet,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ))),
                )
                raw = self.model_call(
                    "prompts/nerv_curiosity_writer_recover.txt",
                    json.dumps(
                        recovery_packet,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    expect_json=True,
                    num_ctx=4096,
                    num_predict=1600,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=CURIOSITY_WRITER_SCHEMA,
                )
        finally:
            self._release("gemma4:12b", "WRITER")
        if not isinstance(raw, dict):
            return {"status": "ignored", "reason": "writer_invalid_output"}
        proposal = raw.get("proposal")
        if proposal is None:
            return {"status": "ignored", "reason": "no_curiosity"}
        if not isinstance(proposal, dict):
            return {"status": "ignored", "reason": "writer_invalid_contract"}
        question = governance.compact_text(proposal.get("question"), 800)
        reason = governance.compact_text(proposal.get("reason"), 600)
        trigger = governance.compact_text(proposal.get("trigger_summary"), 400)
        risk = str(proposal.get("sharing_risk") or "PROHIBITED").upper()
        interest = self._safe_number(proposal.get("interest_score"))
        confidence = self._safe_number(proposal.get("confidence"))
        topic_stage = str(
            proposal.get("topic_stage") or "NEW_OR_SPARSE"
        ).upper()
        current_turn_depth = str(
            proposal.get("current_turn_depth") or "FOUNDATION"
        ).upper()
        question_depth = str(
            proposal.get("question_depth") or "FOUNDATION"
        ).upper()
        foundation_facet = str(
            proposal.get("foundation_facet") or "OTHER_CONCRETE_CONTEXT"
        ).upper()
        breadth_relation = str(
            proposal.get("breadth_relation")
            or "DISTINCT_FOUNDATION_FACET"
        ).upper()
        breadth_fit = proposal.get("breadth_fit", True) is True
        related_curiosity_ids = []
        supplied_curiosity_ids = {
            str(item.get("id") or "")
            for item in recent_history if str(item.get("id") or "")
        }
        for value in proposal.get("related_curiosity_ids") or []:
            value = str(value or "")[:120]
            if value and value not in related_curiosity_ids:
                related_curiosity_ids.append(value)
        related_knowledge_ids = []
        supplied_knowledge_ids = {
            str(item.get("id") or "")
            for item in topic_knowledge if str(item.get("id") or "")
        }
        for value in proposal.get("related_knowledge_ids") or []:
            value = str(value or "")[:160]
            if value and value not in related_knowledge_ids:
                related_knowledge_ids.append(value)
        seed_metadata = seed_metadata if isinstance(seed_metadata, dict) else {}
        seed_kind_normalized = str(seed_kind or "USER_TURN").upper()
        seed_topic_id = str(seed_metadata.get("topic_id") or "")[:80]
        topic_by_knowledge_id = {
            str(item.get("id") or ""): str(item.get("topic_id") or "")[:80]
            for item in topic_knowledge
            if str(item.get("id") or "") and str(item.get("topic_id") or "")
        }
        lifecycle_by_topic_id = {
            str(item.get("topic_id") or ""): str(
                item.get("topic_lifecycle_state") or ""
            )[:40]
            for item in topic_knowledge
            if str(item.get("topic_id") or "")
        }
        proposal_topic_ids = []
        if seed_topic_id:
            proposal_topic_ids.append(seed_topic_id)
        for knowledge_id in related_knowledge_ids:
            topic_id = topic_by_knowledge_id.get(knowledge_id, "")
            if topic_id and topic_id not in proposal_topic_ids:
                proposal_topic_ids.append(topic_id)
        topic_id = seed_topic_id or (
            proposal_topic_ids[0] if len(proposal_topic_ids) == 1 else ""
        )
        topic_lifecycle_state = str(
            seed_metadata.get("topic_lifecycle_state")
            or lifecycle_by_topic_id.get(topic_id)
            or ""
        ).upper()[:40]
        wake_reason = str(seed_metadata.get("wake_reason") or "").upper()[:60]
        if (
            seed_kind_normalized == "USER_TURN"
            and topic_lifecycle_state == "PAUSED_COMPLETE"
        ):
            wake_reason = "USER_REENGAGEMENT"
        depth_fit = proposal.get("depth_fit", True) is True
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
        rejection_reasons = []
        if not question or not reason or not trigger:
            rejection_reasons.append("invalid_contract")
        if risk != "NORMAL":
            rejection_reasons.append("sharing_risk")
        if confidence < MIN_HARD_CONFIDENCE:
            rejection_reasons.append("extremely_low_confidence")
        if not language_matches:
            rejection_reasons.append("language_mismatch")
        if _splits_compound_fandom_label(question, message):
            rejection_reasons.append("compound_label_split")
        if _reasks_identity_already_grounded(
            question,
            message,
            assistant_reply,
            assistant_grounding,
        ):
            rejection_reasons.append("grounded_identity_reask")
        if topic_stage not in {
            "NEW_OR_SPARSE", "DEVELOPING", "SUSTAINED"
        }:
            rejection_reasons.append("invalid_topic_stage")
        if current_turn_depth not in {
            "FOUNDATION", "ADJACENT", "SPECIALIST"
        } or question_depth not in {
            "FOUNDATION", "ADJACENT", "SPECIALIST"
        }:
            rejection_reasons.append("invalid_question_depth")
        if foundation_facet not in {
            "PEOPLE",
            "HISTORY",
            "WORKS_OR_PERFORMANCES",
            "EVENTS_OR_STORIES",
            "RELATIONSHIPS_OR_CULTURE",
            "ORDINARY_BEHAVIOR",
            "STRUCTURE_OR_ROSTER",
            "OTHER_CONCRETE_CONTEXT",
            "SPECIALIST_ANALYSIS",
        }:
            rejection_reasons.append("invalid_foundation_facet")
        if breadth_relation not in {
            "DISTINCT_FOUNDATION_FACET",
            "SAME_NARROW_FACET",
            "PROPORTIONATE_DEEPENING",
        }:
            rejection_reasons.append("invalid_breadth_relation")
        if not set(related_curiosity_ids).issubset(supplied_curiosity_ids):
            rejection_reasons.append("unknown_curiosity_reference")
        if not set(related_knowledge_ids).issubset(supplied_knowledge_ids):
            rejection_reasons.append("unknown_knowledge_reference")
        if seed_kind_normalized in {"TOPIC_GAP", "TOPIC_REFRESH"} and (
            not related_knowledge_ids
            or any(
                topic_by_knowledge_id.get(knowledge_id) != seed_topic_id
                for knowledge_id in related_knowledge_ids
            )
        ):
            rejection_reasons.append("lifecycle_seed_missing_topic_evidence")
        if (
            seed_kind_normalized == "VERIFIED_KNOWLEDGE_IDLE"
            and topic_lifecycle_state == "PAUSED_COMPLETE"
        ):
            rejection_reasons.append("topic_paused_complete")
        if seed_kind_normalized == "TOPIC_GAP" and (
            topic_lifecycle_state != "ACTIVE" or wake_reason != "OPEN_GAP"
        ):
            rejection_reasons.append("invalid_topic_gap_seed")
        if seed_kind_normalized == "TOPIC_REFRESH" and (
            topic_lifecycle_state != "PAUSED_COMPLETE"
            or wake_reason not in {"AUTO_INTEREST_REFRESH", "REVIEW_DUE"}
        ):
            rejection_reasons.append("invalid_topic_refresh_seed")
        if not depth_fit:
            rejection_reasons.append("depth_not_fit")
        if not breadth_fit:
            rejection_reasons.append("breadth_not_fit")
        if (
            topic_stage == "NEW_OR_SPARSE"
            and current_turn_depth != "SPECIALIST"
            and question_depth != "FOUNDATION"
        ):
            rejection_reasons.append("sparse_topic_too_deep")
        if (
            topic_stage == "DEVELOPING"
            and current_turn_depth == "FOUNDATION"
            and question_depth != "FOUNDATION"
        ):
            rejection_reasons.append("foundation_turn_too_deep")
        elif (
            topic_stage == "DEVELOPING"
            and current_turn_depth != "SPECIALIST"
            and question_depth == "SPECIALIST"
        ):
            rejection_reasons.append("developing_topic_too_deep")
        related_support_count = len(
            set(related_curiosity_ids + related_knowledge_ids)
        )
        if (
            question_depth == "SPECIALIST"
            and current_turn_depth != "SPECIALIST"
            and (
                topic_stage != "SUSTAINED"
                or related_support_count < 2
            )
        ):
            rejection_reasons.append("specialist_depth_unsupported")
        if (
            topic_stage in {"NEW_OR_SPARSE", "DEVELOPING"}
            and current_turn_depth == "FOUNDATION"
            and breadth_relation != "DISTINCT_FOUNDATION_FACET"
        ):
            rejection_reasons.append("foundation_breadth_not_expanded")
        if rejection_reasons:
            governance.append_jsonl(
                self.audit_path,
                {
                    "event": "curiosity_proposal_rejected",
                    "rejection_reasons": rejection_reasons,
                    "sharing_risk": risk,
                    "interest_score": interest,
                    "confidence": confidence,
                    "language_matches": language_matches,
                },
            )
            return {
                "status": "dismissed",
                "reason": ",".join(rejection_reasons),
            }

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
            "topic_stage": topic_stage,
            "current_turn_depth": current_turn_depth,
            "question_depth": question_depth,
            "foundation_facet": foundation_facet,
            "breadth_relation": breadth_relation,
            "breadth_fit": True,
            "related_curiosity_ids": related_curiosity_ids,
            "related_knowledge_ids": related_knowledge_ids,
            "depth_fit": True,
            "created_at": now,
            "source": "nerv_ai_curiosity",
            "seed_kind": str(seed_kind or "USER_TURN")[:60],
            "source_curiosity_id": str(
                (seed_metadata or {}).get("source_curiosity_id")
                if isinstance(seed_metadata, dict) else ""
            )[:120] or None,
            "source_knowledge_id": str(
                (seed_metadata or {}).get("source_knowledge_id")
                if isinstance(seed_metadata, dict) else ""
            )[:160] or None,
            "topic_id": topic_id or None,
            "topic_lifecycle_state": topic_lifecycle_state or None,
            "wake_reason": wake_reason or None,
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

    def bind_curated_knowledge(self, topic_links):
        """Attach exact curator-owned topic/layer IDs to related journal rows."""

        links = {
            str(value.get("knowledge_id") or ""): {
                "topic_id": str(value.get("topic_id") or "")[:80],
                "knowledge_layer": str(
                    value.get("knowledge_layer") or ""
                )[:40],
            }
            for value in topic_links or []
            if isinstance(value, dict)
            and str(value.get("knowledge_id") or "")
            and str(value.get("topic_id") or "")
        }
        if not links:
            return {"status": "ignored", "updated": 0}
        updated = 0
        with _LOCK:
            state = self.load()
            for item in state.get("items", []):
                if not isinstance(item, dict):
                    continue
                verification = item.get("verification")
                verification = (
                    verification if isinstance(verification, dict) else {}
                )
                direct_ids = [
                    str(verification.get("knowledge_id") or ""),
                    str(item.get("source_knowledge_id") or ""),
                ]
                matched = [links[value] for value in direct_ids if value in links]
                if not matched:
                    related_topics = {
                        links[value]["topic_id"]
                        for value in item.get("related_knowledge_ids", [])
                        if value in links
                    }
                    if len(related_topics) == 1:
                        topic_id = next(iter(related_topics))
                        matched = [{"topic_id": topic_id, "knowledge_layer": ""}]
                if not matched:
                    continue
                link = matched[0]
                changed = item.get("topic_id") != link["topic_id"]
                item["topic_id"] = link["topic_id"]
                if link.get("knowledge_layer"):
                    changed = (
                        changed
                        or item.get("knowledge_layer")
                        != link["knowledge_layer"]
                    )
                    item["knowledge_layer"] = link["knowledge_layer"]
                if changed:
                    item["topic_bound_at"] = governance.now_iso()
                    updated += 1
            if updated:
                state["revision"] = int(state.get("revision", 0)) + 1
                governance.save_json(self.path, state)
        if updated:
            governance.append_jsonl(
                self.audit_path,
                {"event": "curiosity_topic_links_updated", "count": updated},
            )
        return {"status": "updated" if updated else "unchanged", "updated": updated}

    def topic_interest_signals(self, topic_id):
        """Expose bounded AI-owned interest signals; they are never fact evidence."""

        wanted = str(topic_id or "")
        if not wanted:
            return []
        output = []
        for item in self.load().get("items", []):
            if not isinstance(item, dict) or str(item.get("topic_id") or "") != wanted:
                continue
            # A lifecycle-generated open question cannot amplify its own
            # priority. It becomes a new signal only after independent
            # verification; USER_TURN drafts may still represent renewed user
            # interest before their answer is known.
            if (
                str(item.get("seed_kind") or "").upper()
                in {"TOPIC_GAP", "TOPIC_REFRESH"}
                and self._question_is_open(item)
            ):
                continue
            verification = item.get("verification")
            verification = verification if isinstance(verification, dict) else {}
            output.append({
                "id": str(item.get("id") or "")[:120],
                "question": str(item.get("question") or "")[:300],
                "state": str(item.get("state") or "")[:40],
                "interest_score": self._safe_number(item.get("interest_score")),
                "question_depth": str(item.get("question_depth") or "")[:40],
                "foundation_facet": str(
                    item.get("foundation_facet") or ""
                )[:50],
                "seed_kind": str(item.get("seed_kind") or "")[:60],
                "wake_reason": str(item.get("wake_reason") or "")[:60],
                "created_at": str(item.get("created_at") or "")[:80],
                "verified_at": str(item.get("verified_at") or "")[:80],
                "verification_status": str(
                    verification.get("status") or ""
                )[:40],
            })
        return output[-20:]

    @staticmethod
    def _question_is_open(item):
        if not isinstance(item, dict):
            return False
        if item.get("state") == "DRAFT":
            return True
        if item.get("state") != "ANSWERED_UNVERIFIED":
            return False
        verification = item.get("verification")
        verification = verification if isinstance(verification, dict) else {}
        return str(verification.get("status") or "").upper() not in {
            "SKIPPED",
            "INSUFFICIENT_EVIDENCE",
            "REJECTED",
            "FAILED",
        }

    def open_topic_ids(self):
        """Return topics that already have an unresolved outbound question."""

        return sorted({
            str(item.get("topic_id") or "")
            for item in self.load().get("items", [])
            if isinstance(item, dict)
            and str(item.get("topic_id") or "")
            and self._question_is_open(item)
        })

    def open_lifecycle_topic_ids(self):
        """Keep autonomous topic exploration to one unresolved chain step."""

        return sorted({
            str(item.get("topic_id") or "")
            for item in self.load().get("items", [])
            if isinstance(item, dict)
            and str(item.get("topic_id") or "")
            and self._question_is_open(item)
            and str(item.get("seed_kind") or "").upper()
            in {"TOPIC_GAP", "TOPIC_REFRESH"}
        })

    def observe_topic_lifecycle(self, seed):
        """Draft at most one lifecycle-authorized gap or refresh question."""

        seed = seed if isinstance(seed, dict) else {}
        topic_id = str(seed.get("topic_id") or "")[:80]
        seed_kind = str(seed.get("seed_kind") or "TOPIC_GAP").upper()
        wake_reason = str(seed.get("wake_reason") or "").upper()
        lifecycle = seed.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        lifecycle_state = str(lifecycle.get("state") or "").upper()
        if not topic_id:
            return {"status": "ignored", "reason": "topic_id_missing"}
        if topic_id in self.open_topic_ids():
            return {"status": "ignored", "reason": "topic_question_already_open"}
        if seed_kind == "TOPIC_GAP" and (
            lifecycle_state != "ACTIVE" or wake_reason != "OPEN_GAP"
        ):
            return {"status": "ignored", "reason": "topic_gap_not_authorized"}
        if seed_kind == "TOPIC_REFRESH" and (
            lifecycle_state != "PAUSED_COMPLETE"
            or wake_reason not in {"AUTO_INTEREST_REFRESH", "REVIEW_DUE"}
        ):
            return {"status": "ignored", "reason": "topic_refresh_not_authorized"}
        candidates = [
            item for item in seed.get("knowledge_candidates", [])
            if isinstance(item, dict) and item.get("id")
        ][:10]
        if not candidates:
            return {"status": "ignored", "reason": "topic_knowledge_missing"}
        source_knowledge_id = str(
            seed.get("source_knowledge_id") or candidates[0].get("id") or ""
        )[:160]
        source_claim = str(candidates[0].get("claim") or "")
        title = str(seed.get("title") or candidates[0].get("subject") or "").strip()
        next_focus = str(lifecycle.get("next_focus") or "").strip()
        if seed_kind == "TOPIC_REFRESH":
            next_focus = (
                "复查这个主题自上次验证后是否出现值得更新的变化。"
                if _CJK_RE.search(title + source_claim)
                else "Check whether this topic has a worthwhile verified update."
            )
        message = " — ".join(value for value in (title, next_focus) if value)
        source_curiosity_id = str(seed.get("source_curiosity_id") or "")[:120]
        if not source_curiosity_id:
            source_curiosity_id = next(
                (
                    str(item.get("id") or "")
                    for item in reversed(self.load().get("items", []))
                    if isinstance(item, dict)
                    and str(item.get("topic_id") or "") == topic_id
                    and item.get("state") == "VERIFIED"
                ),
                "",
            )
        return self.observe_turn(
            message or title,
            source_claim,
            "VERIFIED_KNOWLEDGE",
            knowledge_candidates=candidates,
            seed_kind=seed_kind,
            seed_metadata={
                "source_curiosity_id": source_curiosity_id,
                "source_knowledge_id": source_knowledge_id,
                "topic_id": topic_id,
                "topic_lifecycle_state": lifecycle_state,
                "wake_reason": wake_reason,
                "next_focus": next_focus,
                "interest_score": lifecycle.get("interest_score"),
            },
        )

    def observe_verified_knowledge(
        self,
        knowledge_item,
        source_curiosity,
        knowledge_candidates=None,
    ):
        """Let the existing Writer continue from newly verified Knowledge."""
        knowledge_item = (
            knowledge_item if isinstance(knowledge_item, dict) else {}
        )
        source_curiosity = (
            source_curiosity if isinstance(source_curiosity, dict) else {}
        )
        if (
            knowledge_item.get("status") != "verified"
            or not str(knowledge_item.get("claim") or "").strip()
        ):
            return {"status": "ignored", "reason": "knowledge_not_verified"}
        curation = knowledge_item.get("curation")
        curation = curation if isinstance(curation, dict) else {}
        topic_id = str(curation.get("topic_id") or "")
        if curation.get("status") != "curated" or not topic_id:
            return {"status": "ignored", "reason": "awaiting_topic_curation"}
        lifecycle = knowledge_item.get("topic_lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        lifecycle_state = str(lifecycle.get("state") or "").upper()
        if lifecycle_state not in {"ACTIVE", "PAUSED_COMPLETE"}:
            return {"status": "ignored", "reason": "awaiting_topic_assessment"}
        if lifecycle_state == "PAUSED_COMPLETE":
            return {"status": "ignored", "reason": "topic_paused_complete"}
        candidates = list(knowledge_candidates or [])
        if not any(
            isinstance(value, dict)
            and value.get("id") == knowledge_item.get("id")
            for value in candidates
        ):
            candidates.insert(0, knowledge_item)
        return self.observe_topic_lifecycle({
            "topic_id": topic_id,
            "title": str(knowledge_item.get("subject") or "")[:200],
            "lifecycle": lifecycle,
            "knowledge_candidates": candidates[:10],
            "source_knowledge_id": knowledge_item.get("id"),
            "source_curiosity_id": source_curiosity.get("id"),
            "seed_kind": "TOPIC_GAP",
            "wake_reason": "OPEN_GAP",
        })

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
            limit = max(
                0,
                min(
                    MAX_DAILY_LIMIT,
                    int(state.get("daily_limit", DEFAULT_DAILY_LIMIT)),
                ),
            )
        except (TypeError, ValueError):
            limit = DEFAULT_DAILY_LIMIT
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
                "confidence": item.get("confidence"),
                "topic_stage": item.get("topic_stage"),
                "current_turn_depth": item.get("current_turn_depth"),
                "question_depth": item.get("question_depth"),
                "foundation_facet": item.get("foundation_facet"),
                "breadth_relation": item.get("breadth_relation"),
                "breadth_fit": item.get("breadth_fit"),
                "seed_kind": item.get("seed_kind"),
                "source_knowledge_id": item.get("source_knowledge_id"),
                "created_at": item.get("created_at"),
            }
            for item in drafts
        ]
        draft_ids = {
            str(item.get("id") or "")
            for item in drafts
            if str(item.get("id") or "")
        }
        selection_schema = deepcopy(CURIOSITY_SELECTION_SCHEMA)
        selection_schema["properties"]["candidate_id"] = {
            "type": "string",
            "enum": sorted(draft_ids),
        }
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
                model_name="gemma4:12b",
                json_schema=selection_schema,
            )
            decision = str(raw.get("decision") or "").upper() if isinstance(raw, dict) else ""
            selected_id = str(raw.get("candidate_id") or "") if isinstance(raw, dict) else ""

            # A SKIP is audited once because small local models can confuse a
            # named public figure with the user's private identity, or invent a
            # requirement that curiosity must be general science.  Recovery is
            # still an AI semantic decision; Python only validates exact IDs.
            if decision != "ASK" or selected_id not in draft_ids:
                print(
                    "[NERV CURIOSITY SELECT RECOVERY]",
                    "decision=" + (decision or "INVALID"),
                )
                raw = self.model_call(
                    "prompts/nerv_curiosity_select_recovery.txt",
                    json.dumps(
                        {
                            "current_date": datetime.now().date().isoformat(),
                            "drafts": catalog,
                            "first_selection": raw if isinstance(raw, dict) else None,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    expect_json=True,
                    num_ctx=4096,
                    num_predict=420,
                    think=False,
                    model_name="gemma4:12b",
                    json_schema=selection_schema,
                )
        finally:
            self._release("gemma4:12b", "SELECT")

        if not isinstance(raw, dict):
            return None
        decision = str(raw.get("decision") or "").upper()
        selected_id = str(raw.get("candidate_id") or "")
        selected = next(
            (item for item in drafts if item.get("id") == selected_id),
            None,
        )
        if selected is None:
            return None
        if decision == "ASK":
            return selected
        if decision == "SKIP":
            self._dismiss_selection_candidate(
                selected_id,
                raw.get("reason"),
            )
        return None

    def _dismiss_selection_candidate(self, candidate_id, reason):
        """Remove one exact AI-rejected draft so it cannot loop forever."""
        with _LOCK:
            state = self.load()
            item = next(
                (
                    value for value in state.get("items", [])
                    if isinstance(value, dict)
                    and value.get("id") == candidate_id
                ),
                None,
            )
            if item is None or item.get("state") != "DRAFT":
                return
            item["state"] = "DISMISSED"
            item["selection_skipped_at"] = governance.now_iso()
            item["selection_skip_reason"] = governance.compact_text(reason, 600)
            state["revision"] = int(state.get("revision", 0)) + 1
            governance.save_json(self.path, state)
        governance.append_jsonl(
            self.audit_path,
            {
                "event": "curiosity_selection_dismissed",
                "id": candidate_id,
            },
        )
        print(
            "[NERV CURIOSITY DISMISSED]",
            "candidate_id=" + candidate_id,
        )

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
