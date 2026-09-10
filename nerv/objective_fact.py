"""Pre-display verification gate for public objective facts.

The gate is deliberately narrow: cheap deterministic checks keep ordinary
local conversation fast, while a small semantic audit decides whether a
fact-heavy local draft must be rerouted through Casper's existing browser
fact lookup before it can be shown to the user.
"""

import json
import re


OBJECTIVE_FACT_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ALLOW", "VERIFY"]},
        "claim": {"type": "string", "maxLength": 600},
        "reason": {"type": "string", "maxLength": 300},
    },
    "required": ["decision", "claim", "reason"],
    "additionalProperties": False,
}

KNOWLEDGE_CORRECTION_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["NONE", "PERSONAL_AUTHORITY", "OBJECTIVE_DISPUTE"],
        },
        "disputed_knowledge_ids": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 120},
        },
        "claim_to_verify": {"type": "string", "maxLength": 1200},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": [
        "decision", "disputed_knowledge_ids", "claim_to_verify", "reason"
    ],
    "additionalProperties": False,
}

_CHALLENGE_RE = re.compile(
    r"(?:不对|错了|错误|真的吗|真的是|你确定|好像没有|没有吧|"
    r"核实|验证|查证|fact.?check|are you sure|that(?:'s| is) wrong)",
    re.IGNORECASE,
)
_CORRECTION_TRIGGER_RE = re.compile(
    r"(?:不对|错了|错误|记错|更正|纠正|改成|应该是|不是这样|"
    r"我说的是|你说的.{0,20}(?:不对|错)|"
    r"incorrect|correction|correct that|you(?:'re| are) wrong|"
    r"that(?:'s| is) not right|I meant)",
    re.IGNORECASE,
)
_PUBLIC_FACT_RE = re.compile(
    r"(?:当前|现在|最新|截至|现任|名单|成员|分队|队伍|阵容|组织|"
    r"版本|发布日期|成立时间|出生|去世|死亡|还活着|死了|属于|隶属|"
    r"有几个|有哪些|分别是|谁是|官方|官网|公演|"
    r"current|latest|as of|roster|member|team|version|release date|"
    r"founded|born|died|dead|alive|official)",
    re.IGNORECASE,
)
_HIGH_CONSEQUENCE_RE = re.compile(
    r"(?:去世|死亡|死了|还活着|被捕|犯罪|确诊|总统|首相|CEO|"
    r"died|dead|alive|arrested|diagnosed|president|prime minister)",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(
    r"(?:[A-Z][A-Z0-9]{1,}(?:48|\d)?|[A-Za-z]+\d+|\d{4}|"
    r"TEAM\s+[A-Z0-9]+)",
    re.IGNORECASE,
)
_ENUMERATION_RE = re.compile(r"(?:、|，|,|；|;).{0,30}(?:、|，|,|；|;)")
_PERSONAL_AUTHORITY_RE = re.compile(
    r"(?:我的(?:家庭|家人|妈妈|母亲|爸爸|父亲|伴侣|孩子|设备|电脑|"
    r"手机|偏好|喜好|习惯|账号)|我家(?:里|人)?|"
    r"my (?:family|mother|father|partner|child|device|computer|phone|"
    r"preference|account))",
    re.IGNORECASE,
)
_NON_FACT_TASK_RE = re.compile(
    r"(?:翻译|改写|润色|写一|创作|总结这段|算一下|计算|"
    r"translate|rewrite|polish|write (?:a|an)|summarize this|calculate)",
    re.IGNORECASE,
)


def should_audit(message, draft, local_knowledge_context="", plan=None):
    """Return True only when an ungrounded LOCAL draft looks fact-heavy."""
    if str(local_knowledge_context or "").strip():
        return False
    if str((plan or {}).get("response_mode") or "").upper() != "LOCAL_ANSWER":
        return False
    if str((plan or {}).get("interaction_mode") or "TASK").upper() != "TASK":
        return False

    message = str(message or "").strip()
    draft = str(draft or "").strip()
    if not message or not draft:
        return False
    if _PERSONAL_AUTHORITY_RE.search(message):
        return False
    if _NON_FACT_TASK_RE.search(message):
        return False
    if _CHALLENGE_RE.search(message) or _HIGH_CONSEQUENCE_RE.search(message):
        return True

    combined = message + "\n" + draft
    if not _PUBLIC_FACT_RE.search(combined):
        return False
    if _ENTITY_RE.search(combined):
        return True
    if _ENUMERATION_RE.search(draft):
        return True
    # Chinese public-entity questions often contain no Latin capitalization.
    # Concrete roster/identity/time words are enough to request the semantic
    # audit; the audit still owns ALLOW versus VERIFY.
    return bool(
        re.search(
            r"(?:名单|成员|分队|队伍|阵容|现任|谁是|去世|死亡|死了|"
            r"还活着|发布日期|成立时间)",
            combined,
            re.IGNORECASE,
        )
    )


def looks_like_correction(message, recent_context=""):
    """Cheap trigger only; AI owns whether this is a factual correction."""
    message = str(message or "").strip()
    if not message or not str(recent_context or "").strip():
        return False
    # A request to verify/recheck, or a cautious "are you sure?", authorizes
    # fresh research but does not assert that stored Knowledge is wrong.  Only
    # explicit correction language may enter the mutation-capable dispute
    # path.  should_audit() still sends verification-only requests to factual
    # checking without touching Knowledge status.
    return bool(_CORRECTION_TRIGGER_RE.search(message))


def audit_knowledge_correction(
    model_call,
    unload_model,
    message,
    recent_context,
    candidates,
):
    """Let AI distinguish user authority from a disputed objective claim."""
    if not looks_like_correction(message, recent_context):
        return {
            "decision": "NONE",
            "disputed_knowledge_ids": [],
            "claim_to_verify": "",
            "reason": "no_correction_trigger",
        }
    compact_candidates = []
    allowed_ids = set()
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        knowledge_id = str(item.get("id") or "").strip()[:120]
        if not knowledge_id or knowledge_id in allowed_ids:
            continue
        allowed_ids.add(knowledge_id)
        compact_candidates.append({
            "id": knowledge_id,
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:1800],
            "knowledge_type": str(
                item.get("knowledge_type") or "stable"
            )[:20],
            "status": str(item.get("status") or "")[:30],
        })
        if len(compact_candidates) >= 12:
            break
    payload = {
        "current_user_message": str(message or "")[:2400],
        "recent_conversation": str(recent_context or "")[-5000:],
        "active_knowledge_candidates": compact_candidates,
    }
    model_name = "gemma4:12b"
    try:
        raw = model_call(
            "prompts/nerv_knowledge_correction_audit.txt",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=6144,
            num_predict=600,
            think=False,
            model_name=model_name,
            json_schema=KNOWLEDGE_CORRECTION_AUDIT_SCHEMA,
        )
    except Exception as error:
        raw = None
        failure_reason = "knowledge_correction_audit_failed:" + type(error).__name__
    else:
        failure_reason = "invalid_knowledge_correction_audit"
    finally:
        if unload_model is not None:
            try:
                unload_model(model_name)
                print("[NERV KNOWLEDGE CORRECTION MODEL RELEASED]", model_name)
            except Exception as error:
                print(
                    "[NERV KNOWLEDGE CORRECTION MODEL RELEASE WARNING]",
                    repr(error),
                )

    if not isinstance(raw, dict):
        # The trigger itself never authorizes a Knowledge mutation. A failed
        # semantic audit still reroutes a non-personal challenge for checking,
        # but leaves all stored ids untouched.
        decision = (
            "PERSONAL_AUTHORITY"
            if _PERSONAL_AUTHORITY_RE.search(str(message or ""))
            else "OBJECTIVE_DISPUTE"
        )
        return {
            "decision": decision,
            "disputed_knowledge_ids": [],
            "claim_to_verify": str(message or "")[:1200],
            "reason": failure_reason,
        }
    decision = str(raw.get("decision") or "NONE").upper().strip()
    if decision not in {"NONE", "PERSONAL_AUTHORITY", "OBJECTIVE_DISPUTE"}:
        decision = "OBJECTIVE_DISPUTE"
    if (
        decision == "OBJECTIVE_DISPUTE"
        and not _CORRECTION_TRIGGER_RE.search(str(message or ""))
    ):
        decision = "NONE"
        raw["reason"] = "verification_request_without_explicit_correction"
    selected_ids = []
    for value in raw.get("disputed_knowledge_ids", []):
        knowledge_id = str(value or "").strip()
        if (
            knowledge_id in allowed_ids
            and knowledge_id not in selected_ids
        ):
            selected_ids.append(knowledge_id)
    if decision != "OBJECTIVE_DISPUTE":
        selected_ids = []
    claim_to_verify = str(raw.get("claim_to_verify") or "").strip()[:1200]
    if decision == "OBJECTIVE_DISPUTE" and not claim_to_verify:
        claim_to_verify = str(message or "")[:1200]
    return {
        "decision": decision,
        "disputed_knowledge_ids": selected_ids,
        "claim_to_verify": claim_to_verify,
        "reason": str(raw.get("reason") or "")[:500],
    }


def correction_fact_request(message, audit, disputed_items):
    """Create a grounded recheck request without treating the user as proof."""
    claims = [
        {
            "id": str(item.get("id") or "")[:120],
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:1800],
        }
        for item in (disputed_items or [])[:8]
        if isinstance(item, dict)
    ]
    return (
        str(message or "")[:2400]
        + "\n\nKnowledge correction context (not evidence):\n"
        + json.dumps(
            {
                "user_disputes_prior_objective_claim": True,
                "claim_to_verify": str(
                    (audit or {}).get("claim_to_verify") or ""
                )[:1200],
                "disputed_records": claims,
                "instruction": (
                    "Reverify the objective fact from scratch. The user's "
                    "challenge triggers research but is not factual evidence."
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )[:7000]


def replacement_knowledge_ids(search_result):
    """Read ids produced by the governed fallback without inferring meaning."""
    if not isinstance(search_result, dict):
        return []
    fallback = search_result.get("external_ai_fallback")
    fallback = fallback if isinstance(fallback, dict) else {}
    values = []
    single = str(fallback.get("knowledge_id") or "").strip()
    if single:
        values.append(single)
    for value in fallback.get("knowledge_ids", []):
        knowledge_id = str(value or "").strip()
        if knowledge_id and knowledge_id not in values:
            values.append(knowledge_id)
    return values[:12]


def audit_correction_replacements(
    model_call,
    unload_model,
    disputed_items,
    replacement_items,
    verified_answer,
):
    """Let AI map corrected claims; ids are never paired by Python meaning."""
    disputed = [
        {
            "id": str(item.get("id") or "")[:120],
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:2000],
        }
        for item in (disputed_items or [])[:8]
        if isinstance(item, dict) and item.get("id")
    ]
    replacements = [
        {
            "id": str(item.get("id") or "")[:120],
            "subject": str(item.get("subject") or "")[:300],
            "claim": str(item.get("claim") or "")[:2000],
            "knowledge_type": str(
                item.get("knowledge_type") or ""
            )[:30],
        }
        for item in (replacement_items or [])[:12]
        if isinstance(item, dict) and item.get("id")
    ]
    if not disputed:
        return {}
    if not replacements:
        return {item["id"]: [] for item in disputed}
    disputed_ids = {item["id"] for item in disputed}
    replacement_ids = {item["id"] for item in replacements}
    schema = {
        "type": "object",
        "properties": {
            "resolutions": {
                "type": "array",
                "minItems": len(disputed_ids),
                "maxItems": len(disputed_ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "disputed_id": {
                            "type": "string",
                            "enum": sorted(disputed_ids),
                        },
                        "replacement_ids": {
                            "type": "array",
                            "maxItems": len(replacement_ids),
                            "items": {
                                "type": "string",
                                "enum": sorted(replacement_ids),
                            },
                        },
                        "reason": {"type": "string", "maxLength": 500},
                    },
                    "required": [
                        "disputed_id", "replacement_ids", "reason"
                    ],
                    "additionalProperties": False,
                },
            },
            "reason": {"type": "string", "maxLength": 500},
        },
        "required": ["resolutions", "reason"],
        "additionalProperties": False,
    }
    model_name = "gemma4:12b"
    try:
        raw = model_call(
            "prompts/nerv_knowledge_correction_resolution.txt",
            json.dumps(
                {
                    "disputed_knowledge": disputed,
                    "newly_verified_reusable_knowledge": replacements,
                    "verified_current_answer": str(verified_answer or "")[:6000],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=8192,
            num_predict=900,
            think=False,
            model_name=model_name,
            json_schema=schema,
        )
    except Exception as error:
        print(
            "[NERV KNOWLEDGE CORRECTION RESOLUTION]",
            "failed=" + type(error).__name__,
        )
        return {}
    finally:
        if unload_model is not None:
            try:
                unload_model(model_name)
                print(
                    "[NERV KNOWLEDGE CORRECTION RESOLUTION MODEL RELEASED]",
                    model_name,
                )
            except Exception as error:
                print(
                    "[NERV KNOWLEDGE CORRECTION RESOLUTION MODEL RELEASE WARNING]",
                    repr(error),
                )
    if not isinstance(raw, dict) or not isinstance(raw.get("resolutions"), list):
        return {}
    mapping = {}
    for item in raw["resolutions"]:
        if not isinstance(item, dict):
            return {}
        disputed_id = str(item.get("disputed_id") or "")
        if disputed_id not in disputed_ids or disputed_id in mapping:
            return {}
        selected = []
        for value in item.get("replacement_ids", []):
            replacement_id = str(value or "")
            if (
                replacement_id not in replacement_ids
                or replacement_id in selected
            ):
                return {}
            selected.append(replacement_id)
        mapping[disputed_id] = selected
    if set(mapping) != disputed_ids:
        return {}
    return mapping


def audit_draft(model_call, unload_model, message, draft, recent_context=""):
    """Ask a compact local model whether objective grounding is required."""
    payload = {
        "current_user_message": str(message or "")[:2400],
        "unverified_local_draft": str(draft or "")[:3000],
        "recent_conversation": str(recent_context or "")[-2400:],
        "local_verified_knowledge_available": False,
    }
    try:
        raw = model_call(
            "prompts/nerv_objective_fact_audit.txt",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=320,
            think=False,
            model_name="gemma4:e4b",
            json_schema=OBJECTIVE_FACT_AUDIT_SCHEMA,
        )
    except Exception as error:
        # A failed audit may not authorize displaying the suspicious draft.
        return {
            "decision": "VERIFY",
            "claim": str(message or "")[:600],
            "reason": "objective_fact_audit_failed:" + type(error).__name__,
        }
    finally:
        if unload_model is not None:
            try:
                unload_model("gemma4:e4b")
                print("[NERV OBJECTIVE FACT MODEL RELEASED] gemma4:e4b")
            except Exception as error:
                print("[NERV OBJECTIVE FACT MODEL RELEASE WARNING]", repr(error))

    if not isinstance(raw, dict):
        return {
            "decision": "VERIFY",
            "claim": str(message or "")[:600],
            "reason": "invalid_objective_fact_audit",
        }
    decision = str(raw.get("decision") or "").upper().strip()
    if decision not in {"ALLOW", "VERIFY"}:
        decision = "VERIFY"
    return {
        "decision": decision,
        "claim": str(raw.get("claim") or "")[:600],
        "reason": str(raw.get("reason") or "")[:300],
    }


def fact_lookup_plan(original_plan, audit):
    """Build a complete, safety-valid FACT_LOOKUP plan for Casper."""
    plan = dict(original_plan or {})
    inherited_risk = str(plan.get("risk") or "low").lower().strip()
    if inherited_risk not in {"low", "medium", "high"}:
        inherited_risk = "low"
    plan.update(
        {
            "response_mode": "FACT_LOOKUP",
            "needs_search": True,
            "research_depth": "direct_lookup",
            "source_policy": "official_first",
            "research_profile": "official_first",
            "risk": inherited_risk,
            "complexity": "medium",
            "reasoning_profile": "analytical",
            "skill_route": "none",
            "device_scope": None,
            "interaction_mode": "TASK",
            "context_profile": "MINIMAL",
            "needs_balthasar": False,
            "claim_to_verify": str((audit or {}).get("claim") or "")[:600]
            or None,
            "reason": (
                "Pre-display objective fact audit required current public "
                "evidence before the local draft can be shown."
            ),
        }
    )
    return plan


def usable_fact_answer_text(search_result):
    """Return only an answer that passed Casper's fact acceptance contract."""
    if not isinstance(search_result, dict):
        return ""
    if str(search_result.get("status") or "").upper() != "OK":
        return ""
    direct_reply = str(search_result.get("direct_reply") or "").strip()
    if direct_reply:
        return direct_reply[:12000]
    for item in search_result.get("answers", []):
        if not isinstance(item, dict) or item.get("accepted") is not True:
            continue
        answer = str(item.get("answer") or "").strip()
        if answer:
            return answer[:12000]
    return ""


def has_usable_fact_answer(search_result):
    """Accept only Casper fact results that contain an audited answer."""
    return bool(usable_fact_answer_text(search_result))


def unavailable_reply(message):
    """Fail closed in the user's language instead of exposing the draft."""
    if re.search(r"[\u3400-\u9fff]", str(message or "")):
        return "这个问题包含需要核实的客观事实，但我这次没有取得足够可靠的来源，所以先不猜。请稍后再试。"
    return (
        "This question contains objective facts that need verification, but I "
        "could not obtain reliable enough sources this time, so I will not guess."
    )
