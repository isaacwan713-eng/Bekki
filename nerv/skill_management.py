"""AI-resolved, confirmation-gated management of verified Casper skills."""

import json


RESOLUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["FORGET", "CLARIFY", "OTHER"],
        },
        "skill_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "reason": {"type": "string"},
    },
    "required": ["decision", "skill_id", "reason"],
    "additionalProperties": False,
}

CONFIRMATION_VALUES = {"CONFIRM", "REJECT", "NEW_REQUEST", "AMBIGUOUS"}


def _safe_catalog(skills):
    catalog = []
    for item in skills if isinstance(skills, list) else []:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("id") or "").strip()
        if not skill_id.startswith("skill_"):
            continue
        catalog.append(
            {
                "id": skill_id[:120],
                "capability": str(item.get("capability") or "")[:120],
                "skill_scope": str(item.get("skill_scope") or "")[:80],
                "target_app": str(item.get("target_app") or "")[:160],
                "content_kind": str(item.get("content_kind") or "")[:100],
                "intent_summary": str(item.get("intent_summary") or "")[:300],
            }
        )
    return catalog[:100]


def resolve_forget_request(message, skills, model_call, unload_model=None):
    """Let the reliable model select one exact ID from a bounded catalog."""
    catalog = _safe_catalog(skills)
    if not catalog:
        return {"status": "EMPTY", "skill": None, "reason": "no verified skills"}

    raw = None
    try:
        raw = model_call(
            "prompts/nerv_skill_forget_resolver.txt",
            json.dumps(
                {
                    "current_user_message": str(message or "")[:1200],
                    "verified_skill_catalog": catalog,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=True,
            num_ctx=3072,
            num_predict=260,
            think=False,
            model_name="gemma4:12b",
            json_schema=RESOLUTION_SCHEMA,
        )
    except Exception as error:
        print("[NERV SKILL MANAGER WARNING]", repr(error))
    finally:
        if unload_model is not None:
            try:
                unload_model("gemma4:12b")
                print("[NERV SKILL MANAGER MODEL RELEASED] gemma4:12b")
            except Exception as error:
                print("[NERV SKILL MANAGER RELEASE WARNING]", repr(error))

    if not isinstance(raw, dict):
        return {"status": "CLARIFY", "skill": None, "reason": "invalid model output"}
    decision = str(raw.get("decision") or "").upper().strip()
    selected_id = str(raw.get("skill_id") or "").strip()
    known = {item["id"]: item for item in catalog}
    if decision == "FORGET" and selected_id in known:
        return {
            "status": "MATCHED",
            "skill": known[selected_id],
            "reason": str(raw.get("reason") or "")[:240],
        }
    if decision == "OTHER":
        return {"status": "OTHER", "skill": None, "reason": str(raw.get("reason") or "")[:240]}
    return {"status": "CLARIFY", "skill": None, "reason": str(raw.get("reason") or "")[:240]}


def classify_forget_confirmation(message, pending_action, model_call, unload_model=None):
    """Classify the next turn without treating a new request as confirmation."""
    raw = ""
    try:
        raw = model_call(
            "prompts/nerv_skill_forget_confirmation.txt",
            json.dumps(
                {
                    "current_user_message": str(message or "")[:800],
                    "pending_skill": (pending_action or {}).get("approval_payload") or {},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            expect_json=False,
            num_ctx=2048,
            num_predict=30,
            think=False,
            model_name="gemma4:12b",
        )
    except Exception as error:
        print("[NERV SKILL CONFIRM WARNING]", repr(error))
    finally:
        if unload_model is not None:
            try:
                unload_model("gemma4:12b")
                print("[NERV SKILL CONFIRM MODEL RELEASED] gemma4:12b")
            except Exception as error:
                print("[NERV SKILL CONFIRM RELEASE WARNING]", repr(error))
    value = str(raw or "").strip().upper()
    return value if value in CONFIRMATION_VALUES else "AMBIGUOUS"


def display_name(skill, language="zh-CN"):
    skill = skill if isinstance(skill, dict) else {}
    target = str(skill.get("target_app") or "").strip()
    kind = str(skill.get("content_kind") or "").strip()
    scope = str(skill.get("skill_scope") or "").strip()
    if language == "zh-CN" and scope == "OPEN_DESTINATION_FOLDER" and target:
        shown = {"tactic": "战术", "tactics": "战术"}.get(kind.casefold(), kind)
        return "打开 " + target + " 的" + (shown or "内容") + "文件夹"
    return str(skill.get("intent_summary") or target or "该技能")[:300]
