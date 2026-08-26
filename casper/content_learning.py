"""Learn and locally verify how one game-content type is installed."""

import json
import os
import sys

from . import browser
from . import game_content
from . import skill_registry


MAX_SOURCES = 12
MAX_READ = 6
ALLOWED_LEARNING_SCOPES = frozenset({
    "OPEN_DESTINATION_FOLDER",
    "INSTALL_CONTENT",
})


# AI owns the semantic adapter selection.  This table is only the executable
# boundary for an adapter that has already been selected: it prevents an
# incompatible file contract from being handed to bounded local I/O.
ADAPTER_CONTRACTS = {
    "FM_TACTIC": {
        "expected_file_types": {".fmf"},
        "destination_kind": "fm_tactic_destination",
        "skill_scopes": {
            "OPEN_DESTINATION_FOLDER",
            "INSTALL_CONTENT",
        },
    },
}


def _ai(
    prompt,
    payload,
    num_predict,
    num_ctx=8192,
    model_name="gemma3:12b",
):
    import tools

    return tools.run_ai_prompt(
        prompt,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        expect_json=True,
        num_ctx=num_ctx,
        num_predict=num_predict,
        think=False,
        model_name=model_name,
    )


def _strings(values, maximum, length):
    if not isinstance(values, list):
        return []
    return [
        str(value).strip()[:length]
        for value in values
        if isinstance(value, str) and value.strip()
    ][:maximum]


def _normalize_learning_plan(result, requested_skill_scope):
    """Normalize only the closed structural contract of an AI plan."""
    if not isinstance(result, dict) or result.get("supported") is not True:
        return None
    capability = str(result.get("capability") or "").strip()[:120]
    target_app = str(result.get("target_app") or "").strip()[:160]
    content_kind = str(result.get("content_kind") or "").strip()[:100]
    skill_scope = str(result.get("skill_scope") or "").strip()[:80]
    if (
        not capability
        or not capability.casefold().startswith("game_content.")
        or not target_app
        or not content_kind
        or skill_scope not in ALLOWED_LEARNING_SCOPES
        or (
            requested_skill_scope
            and skill_scope != requested_skill_scope
        )
    ):
        return None
    return {
        "capability": capability,
        "skill_scope": skill_scope,
        "intent_summary": str(result.get("intent_summary") or "")[:400],
        "target_app": target_app,
        "content_kind": content_kind,
        "parameters": _strings(result.get("parameters"), 12, 100),
        "version_constraints": _strings(
            result.get("version_constraints"), 8, 120
        ),
        "installation_queries": _strings(
            result.get("installation_queries"), 3, 240
        ),
    }


def _review_learning_plan_grounding(message, recent_context, plan):
    """Let AI verify plan identity against the authoritative current turn."""
    payload = {
        "CURRENT_REQUEST": str(message)[:900],
        "REFERENCE_CONTEXT": str(recent_context)[-1500:],
        "PROPOSED_PLAN": {
            key: plan.get(key)
            for key in (
                "skill_scope",
                "capability",
                "intent_summary",
                "target_app",
                "content_kind",
                "parameters",
                "version_constraints",
            )
        },
    }
    attempts = (
        (
            "prompts/casper_content_learning_grounding_review.txt",
            700,
            4096,
        ),
        (
            "prompts/casper_content_learning_grounding_review_retry.txt",
            1400,
            8192,
        ),
    )
    for prompt_path, output_budget, context_budget in attempts:
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=context_budget,
            model_name="gemma3:12b",
        )
        if isinstance(result, dict) and isinstance(
            result.get("grounded"), bool
        ):
            return result["grounded"], str(
                result.get("reason") or ""
            )[:500]
        payload["PREVIOUS_INVALID_OUTPUT"] = result
    return False, "Learning-plan grounding review returned no valid verdict."


def _repair_documentation_queries(
    message,
    plan,
    rejected_queries=None,
    review_reason="",
):
    """Ask focused AI for queries without regenerating grounded identity."""
    payload = {
        "CURRENT_REQUEST": str(message)[:900],
        "GROUNDED_PLAN": {
            key: plan.get(key)
            for key in (
                "skill_scope",
                "capability",
                "target_app",
                "content_kind",
                "version_constraints",
            )
        },
        "REJECTED_QUERIES": _strings(rejected_queries, 3, 240),
        "REVIEW_REASON": str(review_reason or "")[:500],
    }
    attempts = (
        (
            "prompts/casper_content_learning_query.txt",
            1000,
            4096,
        ),
        (
            "prompts/casper_content_learning_query_retry.txt",
            1800,
            8192,
        ),
    )
    if payload["REJECTED_QUERIES"]:
        attempts = attempts[1:]
    for prompt_path, output_budget, context_budget in attempts:
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=context_budget,
            model_name="gemma3:12b",
        )
        queries = _strings(
            result.get("installation_queries")
            if isinstance(result, dict)
            else None,
            3,
            240,
        )
        if queries:
            return queries
        payload["PREVIOUS_INVALID_OUTPUT"] = result
    return []


def _review_documentation_queries(message, plan):
    """Let focused AI review query meaning; Python accepts only its bool."""
    payload = {
        "CURRENT_REQUEST": str(message)[:900],
        "PROPOSED_PLAN": plan,
    }
    attempts = (
        (
            "prompts/casper_content_learning_query_review.txt",
            700,
            4096,
        ),
        (
            "prompts/casper_content_learning_query_review_retry.txt",
            1400,
            8192,
        ),
    )
    for prompt_path, output_budget, context_budget in attempts:
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=context_budget,
            model_name="gemma3:12b",
        )
        if isinstance(result, dict) and isinstance(
            result.get("compliant"), bool
        ):
            return result["compliant"], str(
                result.get("reason") or ""
            )[:500]
        payload["PREVIOUS_INVALID_OUTPUT"] = result
    return False, "Documentation-query review returned no valid verdict."


def _plan(message, recent_context, requested_skill_scope=""):
    payload = {
        "CURRENT_REQUEST": str(message)[:900],
        "REFERENCE_CONTEXT": str(recent_context)[-1500:],
    }
    if requested_skill_scope:
        payload["requested_skill_scope"] = str(requested_skill_scope)[:80]
    attempts = (
        (
            "prompts/casper_content_learning_plan.txt",
            2200,
            8192,
        ),
        (
            "prompts/casper_content_learning_plan_retry.txt",
            3600,
            8192,
        ),
    )
    plan = None
    for prompt_path, output_budget, context_budget in attempts:
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=context_budget,
            model_name="gemma3:12b",
        )
        draft = _normalize_learning_plan(result, requested_skill_scope)
        if draft:
            grounded, grounding_reason = _review_learning_plan_grounding(
                message, recent_context, draft
            )
        else:
            grounded, grounding_reason = False, "invalid structural plan"
        if draft and grounded:
            plan = draft
            break
        payload["PREVIOUS_INVALID_OUTPUT"] = result
        payload["PREVIOUS_GROUNDING_REVIEW"] = grounding_reason
    if not plan:
        return None

    queries = plan["installation_queries"]
    if not queries:
        queries = _repair_documentation_queries(message, plan)
    if not queries:
        return None
    plan["installation_queries"] = queries

    compliant, reason = _review_documentation_queries(message, plan)
    if not compliant:
        queries = _repair_documentation_queries(
            message,
            plan,
            rejected_queries=queries,
            review_reason=reason,
        )
        if not queries:
            return None
        plan["installation_queries"] = queries
        compliant, _reason = _review_documentation_queries(message, plan)
    return plan if compliant else None


def _discover(plan, status_callback=None):
    items, seen = [], set()
    for query in plan["installation_queries"]:
        if status_callback:
            status_callback("Casper 正在学习内容安装方法… 📚")
        result = browser.discover_web(
            query,
            count=6,
            status_callback=status_callback,
            multi_engine=True,
        )
        if result.get("status") == "HUMAN_HANDOFF":
            return items, result.get("event") or "access_block"
        for raw in result.get("results", []):
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "id": _source_id(url),
                "title": str(raw.get("title") or "")[:240],
                "description": str(raw.get("description") or "")[:700],
                "domain": str(raw.get("domain") or "")[:180],
                "url": url,
            })
            if len(items) >= MAX_SOURCES:
                return items, None
    return items, None


def _source_id(url):
    import hashlib

    return hashlib.sha256(str(url).encode("utf-8", errors="ignore")).hexdigest()[:16]


def _rank(plan, discovered):
    payload = {
        "learning_plan": plan,
        "sources": [
            {key: item[key] for key in ("id", "title", "description", "domain")}
            for item in discovered
        ],
    }
    result = _ai("prompts/casper_content_learning_source_rank.txt", payload, 2200)
    if not isinstance(result, dict) or not isinstance(
        result.get("ordered_source_ids"), list
    ):
        payload["retry_instruction"] = (
            "Return only the compact ordered_source_ids JSON now."
        )
        result = _ai(
            "prompts/casper_content_learning_source_rank.txt",
            payload,
            1800,
        )
    if not isinstance(result, dict) or not isinstance(
        result.get("ordered_source_ids"), list
    ):
        return []
    by_id = {item["id"]: item for item in discovered}
    selected = []
    for value in result["ordered_source_ids"]:
        item = by_id.get(str(value))
        if item and item not in selected:
            selected.append(item)
        if len(selected) >= MAX_READ:
            break
    return selected


def _read(ranked, status_callback=None):
    pages = []
    for item in ranked[:MAX_READ]:
        if status_callback:
            status_callback("Casper 正在核对安装教程… 📖")
        page = browser.read_url(item["url"])
        if page.get("success") and not page.get("protected_event"):
            pages.append({
                "source_id": item["id"],
                "title": item["title"],
                "domain": item["domain"],
                "url": item["url"],
                "content": str(page.get("content") or "")[:7000],
            })
    return pages


def _extract_procedure(plan, pages):
    payload = {
        "learning_plan": plan,
        "pages": [
            {key: value for key, value in page.items() if key != "url"}
            for page in pages
        ],
    }
    result = _ai(
        "prompts/casper_content_procedure_extract.txt",
        payload,
        3000,
        num_ctx=16384,
    )
    if not isinstance(result, dict):
        payload["retry_instruction"] = (
            "Return only the compact installation procedure JSON now."
        )
        result = _ai(
            "prompts/casper_content_procedure_extract.txt",
            payload,
            2600,
            num_ctx=16384,
        )
    if not isinstance(result, dict):
        return None
    source_ids = _strings(result.get("source_ids"), 8, 40)
    pages_by_id = {page["source_id"]: page for page in pages}
    source_ids = [value for value in source_ids if value in pages_by_id]
    expected = _strings(result.get("expected_file_types"), 12, 24)
    destinations = _strings(result.get("destination_hints"), 10, 300)
    steps = _strings(result.get("installation_steps"), 14, 400)
    declared_scope = str(result.get("skill_scope") or "").strip()[:80]
    required_scope = str(plan.get("skill_scope") or "").strip()[:80]
    if not source_ids or not expected or not destinations or not steps:
        return None
    if required_scope and declared_scope != required_scope:
        return None
    # The learning plan was independently grounded against the current user
    # request before web evidence was read. Tutorial extraction may describe
    # adjacent installation steps, but those steps must not broaden a declared
    # open-folder skill into copying or installing content.
    if required_scope == "OPEN_DESTINATION_FOLDER":
        capability = str(plan.get("capability") or "").strip()[:120]
        intent_summary = str(
            plan.get("intent_summary") or ""
        ).strip()[:400]
        parameters = _strings(plan.get("parameters"), 12, 100)
    else:
        capability = str(
            result.get("capability") or plan["capability"]
        ).strip()[:120]
        intent_summary = str(
            result.get("intent_summary")
            or plan.get("intent_summary")
            or ""
        ).strip()[:400]
        parameters = _strings(
            result.get("parameters") or plan.get("parameters"), 12, 100
        )
    return {
        "capability": capability,
        "skill_scope": declared_scope or required_scope,
        "intent_summary": intent_summary,
        "target_app": str(result.get("target_app") or plan["target_app"])[:160],
        "content_kind": str(result.get("content_kind") or plan["content_kind"])[:100],
        "parameters": parameters,
        "version_constraints": plan.get("version_constraints", [])[:8],
        "expected_file_types": expected,
        "destination_hints": destinations,
        "installation_steps": steps,
        "post_install_steps": _strings(result.get("post_install_steps"), 10, 300),
        "evidence_summary": str(result.get("evidence_summary") or "")[:700],
        "source_ids": source_ids,
        "source_urls": [pages_by_id[value]["url"] for value in source_ids],
    }


def _select_local_adapter(plan, procedure):
    payload = {"learning_plan": plan, "procedure": procedure}
    for prompt_path, output_budget in (
        ("prompts/casper_content_local_adapter.txt", 260),
        ("prompts/casper_content_local_adapter_retry.txt", 420),
    ):
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=3072,
            model_name="llama3.2:latest",
        )
        value = (
            str(result.get("adapter") or "").upper().strip()
            if isinstance(result, dict)
            else ""
        )
        if value in {"FM_TACTIC", "UNSUPPORTED"}:
            return value
    return ""


def _select_destination(plan, procedure, destinations):
    payload = {
        "learning_plan": plan,
        "procedure": {
            key: procedure.get(key)
            for key in ("destination_hints", "installation_steps")
        },
        "destinations": [
            {"id": item["id"], "name": item["name"]}
            for item in destinations
        ],
    }
    valid_ids = {str(item["id"]) for item in destinations}
    for prompt_path, output_budget in (
        ("prompts/casper_content_destination_select.txt", 320),
        ("prompts/casper_content_destination_select_retry.txt", 520),
    ):
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=4096,
            model_name="llama3.2:latest",
        )
        selected_id = (
            str(result.get("destination_id") or "")
            if isinstance(result, dict)
            else ""
        )
        if selected_id in valid_ids:
            return next(
                item for item in destinations
                if str(item["id"]) == selected_id
            )
    return None


def _review_local_binding(plan, procedure, adapter, destination):
    payload = {
        "learning_plan": plan,
        "procedure": {
            key: procedure.get(key)
            for key in (
                "target_app",
                "content_kind",
                "expected_file_types",
                "destination_hints",
                "installation_steps",
            )
        },
        "selected_adapter": adapter,
        "selected_destination": {
            "id": destination.get("id"),
            "name": destination.get("name"),
        },
    }
    for output_budget in (700, 1200):
        result = _ai(
            "prompts/casper_content_local_binding_review.txt",
            payload,
            output_budget,
            num_ctx=4096,
            model_name="gemma3:12b",
        )
        if isinstance(result, dict) and isinstance(
            result.get("compatible"), bool
        ):
            return result["compatible"]
        payload["retry_instruction"] = (
            "Return only the compact compatible JSON contract now."
        )
    return False


def _validate_adapter_contract(procedure, adapter, destination):
    """Validate only the exact executable contract of an AI-selected adapter."""
    contract = ADAPTER_CONTRACTS.get(str(adapter or "").strip().upper())
    if not contract or not isinstance(procedure, dict) or not isinstance(
        destination, dict
    ):
        return False
    declared_types = {
        str(value or "").strip().casefold()
        for value in procedure.get("expected_file_types", [])
        if isinstance(value, str) and str(value).strip().startswith(".")
    }
    declared_scope = str(procedure.get("skill_scope") or "").strip()
    destination_kind = str(destination.get("kind") or "").strip()
    return (
        declared_types == contract["expected_file_types"]
        and declared_scope in contract["skill_scopes"]
        and destination_kind == contract["destination_kind"]
    )


def _prepare_local_destination(plan, procedure):
    adapter = _select_local_adapter(plan, procedure)
    if adapter != "FM_TACTIC":
        return None, "暂时还没有这个内容类型的本地安装适配器。"
    destinations = game_content.discover_fm_tactic_destinations()
    if not destinations:
        return None, (
            "没有发现 Sports Interactive 下的现有游戏用户数据目录；"
            "请先运行一次目标游戏，让它创建用户数据文件夹。"
        )
    destination = _select_destination(plan, procedure, destinations)
    if not destination:
        return None, "没有可靠地选中这台电脑上的目标内容目录。"
    if not _review_local_binding(plan, procedure, adapter, destination):
        return None, (
            "学习到的应用、内容文件类型和本地目录彼此不一致，"
            "已停止且不会建立临时技能。"
        )
    if not _validate_adapter_contract(procedure, adapter, destination):
        return None, (
            "AI 选择的本地适配器未通过文件类型、技能范围和目标目录的"
            "执行契约检查；已停止且不会建立临时技能。"
        )
    try:
        os.makedirs(destination["path"], exist_ok=True)
        if sys.platform != "win32":
            return None, "本地目录打开功能目前仅支持 Windows。"
        os.startfile(destination["path"])
    except OSError as error:
        return None, "打开本地战术目录失败：" + str(error)[:240]
    procedure["local_adapter"] = adapter
    procedure["destination_kind"] = str(destination.get("kind") or "")
    return destination, ""


def execute(
    message,
    recent_context,
    status_callback=None,
    requested_skill_scope="",
):
    plan = _plan(
        message,
        recent_context,
        requested_skill_scope=requested_skill_scope,
    )
    if not plan:
        return _clarify("没有可靠地形成安装方法学习计划。")
    discovered, protected = _discover(plan, status_callback)
    if protected:
        return {
            "success": False,
            "completed": False,
            "needs_clarification": False,
            "protected_event": protected,
            "reason": "An installation tutorial requires browser verification.",
        }
    if not discovered:
        return _clarify("没有找到可供核对的目标应用文档来源。")
    ranked = _rank(plan, discovered)
    if not ranked:
        return _clarify("搜索结果没有通过目标应用与内容类型的来源筛选。")
    pages = _read(ranked, status_callback)
    if not pages:
        return _clarify("没有成功读取可验证的安装或目录文档页面。")
    procedure = _extract_procedure(plan, pages)
    if not procedure:
        return _clarify("没有从网页证据中学到足够可靠的安装方法。")
    destination, error = _prepare_local_destination(plan, procedure)
    if not destination:
        return _clarify(error)
    candidate = skill_registry.create_pending(procedure, destination, message)
    if not candidate:
        return _clarify("安装方法已形成，但没有成功建立临时技能候选。")
    if requested_skill_scope == "OPEN_DESTINATION_FOLDER":
        opened = {
            "success": True,
            "completed": True,
            "action": "opened_fm_tactic_folder",
            "name": destination["name"],
            "destination": destination["name"],
        }
        marked = skill_registry.mark_execution_success(
            candidate["id"], opened
        )
        if not marked:
            skill_registry.discard_pending(
                candidate["id"],
                "The opened folder could not be machine-verified.",
            )
            return _clarify("战术文件夹已经打开，但临时技能验证失败；未写入 Skills。")
        return {
            **opened,
            "action": "folder_skill_awaiting_user_verification",
            "requires_user_verification": True,
            "verification_kind": "opened_destination_folder",
            "skill_candidate_id": marked["id"],
            "target_app": marked["target_app"],
            "content_kind": marked["content_kind"],
            "destination_name": marked["destination_name"],
            "original_request": str(message)[:900],
            "reason": (
                "The folder opened successfully, but this folder-opening skill "
                "remains pending until the user verifies the destination."
            ),
        }
    return {
        "success": True,
        "completed": False,
        "needs_clarification": False,
        "action": "learned_content_skill_candidate",
        "requires_continuation": True,
        "skill_candidate_id": candidate["id"],
        "target_app": candidate["target_app"],
        "content_kind": candidate["content_kind"],
        "destination_name": candidate["destination_name"],
        "original_request": str(message)[:900],
        "reason": "Installation method learned and stored only as an unverified candidate.",
    }


def reopen_verified_folder(skill):
    if not isinstance(skill, dict) or skill.get("status") != "verified":
        return _clarify("没有可复用的已验证文件夹技能。")
    if skill.get("skill_scope") != "OPEN_DESTINATION_FOLDER":
        return _clarify("匹配到的技能不是打开内容目录的技能。")
    result = game_content.open_verified_fm_tactic_destination(
        skill.get("verified_destination_path", "")
    )
    if result.get("success") and result.get("completed"):
        skill_registry.record_verified_reuse(skill.get("id"))
    return result


def _clarify(message):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": message,
        "reason": message,
    }
