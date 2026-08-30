"""Research public game content and produce a bounded installation manifest."""

import hashlib
import json

from . import browser


MAX_QUERIES = 3
MAX_DISCOVERED = 18
MAX_READ = 8


def _ai(
    prompt,
    payload,
    num_predict,
    num_ctx=8192,
    model_name="gemma4:12b",
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


def _opaque_source_id(url):
    return hashlib.sha256(
        str(url).encode("utf-8", errors="ignore")
    ).hexdigest()[:16]


def _plan(message, recent_context, procedure=None):
    payload = {
        "request": str(message)[:900],
        "recent_context": str(recent_context)[-900:],
    }
    if isinstance(procedure, dict):
        payload["learned_installation_procedure"] = {
            key: procedure.get(key)
            for key in (
                "target_app",
                "content_kind",
                "version_constraints",
                "expected_file_types",
                "evidence_summary",
            )
        }
    attempts = (
        ("prompts/casper_content_research_plan.txt", 700),
        ("prompts/casper_content_research_plan_retry.txt", 900),
    )
    for attempt, (prompt_path, output_budget) in enumerate(attempts):
        if attempt:
            payload = {
                "request": str(message)[:700],
                "retry_instruction": (
                    "Return exactly the compact research-plan JSON contract."
                ),
            }
            if isinstance(procedure, dict):
                payload["learned_installation_procedure"] = {
                    key: procedure.get(key)
                    for key in (
                        "target_app",
                        "content_kind",
                        "version_constraints",
                        "expected_file_types",
                    )
                }
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=4096,
            model_name="llama3.2:latest",
        )
        if not isinstance(result, dict):
            continue
        queries = [
            str(value).strip()[:240]
            for value in result.get("queries", [])
            if str(value).strip()
        ][:MAX_QUERIES]
        if not queries:
            continue
        target_app = str(result.get("target_app") or "").strip()[:160]
        content_kind = str(result.get("content_kind") or "").strip()[:100]
        version_constraints = _strings(
            result.get("version_constraints"), 8, 120
        )
        fit_context = _distinct_fit_context(
            _strings(result.get("fit_context"), 10, 140),
            target_app,
            content_kind,
            version_constraints,
        )
        return {
            "target_app": target_app,
            "content_kind": content_kind,
            "requested_outcome": str(result.get("requested_outcome") or "").strip()[:300],
            "fit_context": fit_context,
            "fit_context_is_content_identity": (
                result.get("fit_context_is_content_identity") is True
            ),
            "version_constraints": version_constraints,
            "selection_criteria": _strings(result.get("selection_criteria"), 10, 140),
            "queries": queries,
        }
    return None


def _strings(values, maximum, length):
    if not isinstance(values, list):
        return []
    return [str(value).strip()[:length] for value in values if str(value).strip()][
        :maximum
    ]


def _distinct_fit_context(values, target_app, content_kind, versions):
    structural = {
        str(value).strip().casefold()
        for value in [target_app, content_kind, *versions]
        if str(value).strip()
    }
    return [value for value in values if value.casefold() not in structural]


def _review_queries(message, plan):
    payload = {
            "request": str(message)[:700],
            "target_app": plan["target_app"],
            "content_kind": plan["content_kind"],
            "fit_context": plan.get("fit_context", []),
            "fit_context_is_content_identity": plan.get(
                "fit_context_is_content_identity", False
            ),
            "version_constraints": plan["version_constraints"],
            "selection_criteria": plan["selection_criteria"],
            "proposed_queries": plan["queries"],
    }
    attempts = (
        ("prompts/casper_content_query_review.txt", 500),
        ("prompts/casper_content_query_review_retry.txt", 650),
        ("prompts/casper_content_query_review_retry.txt", 800),
    )
    for attempt, (prompt_path, output_budget) in enumerate(attempts):
        if attempt == 1:
            payload = dict(payload)
            payload["retry_instruction"] = (
                "Return only {\"queries\":[...]}. Remove fit context from every "
                "query. Do not echo other input fields."
            )
        elif attempt == 2:
            payload = {
                "target_app": plan["target_app"],
                "content_kind": plan["content_kind"],
                "version_constraints": plan["version_constraints"],
                "objective": "Find strong downloadable universal content with performance evidence.",
                "retry_instruction": (
                    "Return only {\"queries\":[...]}. Use universal discovery. "
                    "Do not include any team, character, roster, hardware, or "
                    "play-style name."
                ),
            }
        result = _ai(
            prompt_path,
            payload,
            output_budget,
            num_ctx=4096,
            model_name="llama3.2:latest",
        )
        reviewed = (
            _strings(result.get("queries"), MAX_QUERIES, 240)
            if isinstance(result, dict)
            else []
        )
        if reviewed and _queries_are_compliant(message, plan, reviewed):
            reviewed_plan = dict(plan)
            reviewed_plan["queries"] = reviewed
            return reviewed_plan
    return None


def _queries_are_compliant(message, plan, queries):
    payload = {
        "target_app": plan["target_app"],
        "content_kind": plan["content_kind"],
        "version_constraints": plan.get("version_constraints", []),
        "fit_context": plan.get("fit_context", []),
        "fit_context_is_content_identity": plan.get(
            "fit_context_is_content_identity", False
        ),
        "queries": queries,
    }
    first = _ai(
        "prompts/casper_content_query_compliance.txt",
        payload,
        420,
        num_ctx=3072,
        model_name="llama3.2:latest",
    )
    if isinstance(first, dict) and first.get("compliant") is True:
        return True

    adjudication_payload = dict(payload)
    adjudication_payload["first_ai_decision"] = first
    adjudicated = _ai(
        "prompts/casper_content_query_compliance_retry.txt",
        adjudication_payload,
        1200,
        num_ctx=4096,
        model_name="gemma4:12b",
    )
    return (
        isinstance(adjudicated, dict)
        and adjudicated.get("compliant") is True
    )


def _discover(plan, status_callback=None):
    discovered = []
    seen = set()
    for query in plan["queries"]:
        if status_callback:
            status_callback("Casper 正在搜索内容与安装教程… 🔎")
        result = browser.discover_web(
            query,
            count=6,
            status_callback=status_callback,
            multi_engine=True,
        )
        if result.get("status") == "HUMAN_HANDOFF":
            return discovered, result.get("event") or "access_block"
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            discovered.append(
                {
                    "id": _opaque_source_id(url),
                    "title": str(item.get("title") or "")[:240],
                    "description": str(item.get("description") or "")[:700],
                    "domain": str(item.get("domain") or "")[:180],
                    "url": url,
                    "query": query,
                }
            )
            if len(discovered) >= MAX_DISCOVERED:
                return discovered, None
    return discovered, None


def _rank_discovered(message, plan, discovered):
    discovery_plan = {
        key: plan[key]
        for key in (
            "target_app",
            "content_kind",
            "requested_outcome",
            "version_constraints",
            "queries",
        )
        if key in plan
    }
    payload = {
        "research_plan": discovery_plan,
        "sources": [
            {
                "id": item["id"],
                "title": item["title"],
                "description": item["description"],
                "domain": item["domain"],
            }
            for item in discovered
        ],
    }
    result = _ai(
        "prompts/casper_content_source_rank.txt",
        payload,
        2000,
    )
    if not (
        isinstance(result, dict)
        and isinstance(result.get("ordered_source_ids"), list)
    ):
        result = _ai(
            "prompts/casper_content_source_rank_retry.txt",
            {
                **payload,
                "previous_invalid_output": result,
            },
            1800,
        )
    ids = (
        _strings(result.get("ordered_source_ids"), MAX_READ, 40)
        if isinstance(result, dict)
        else []
    )
    by_id = {item["id"]: item for item in discovered}
    return [by_id[source_id] for source_id in ids if source_id in by_id]


def _retry_queries(message, plan, discovered):
    discovery_plan = {
        key: plan[key]
        for key in (
            "target_app",
            "content_kind",
            "requested_outcome",
            "version_constraints",
        )
        if key in plan
    }
    result = _ai(
        "prompts/casper_content_query_retry.txt",
        {
            "research_plan": discovery_plan,
            "irrelevant_results": [
                {
                    "title": item["title"],
                    "description": item["description"],
                    "domain": item["domain"],
                }
                for item in discovered[:12]
            ],
        },
        700,
    )
    queries = (
        _strings(result.get("queries"), 2, 240)
        if isinstance(result, dict)
        else []
    )
    return queries if queries and _queries_are_compliant(message, plan, queries) else []


def _read_candidates(discovered, status_callback=None):
    pages = []
    for item in discovered[:MAX_READ]:
        if status_callback:
            status_callback("Casper 正在阅读候选页面和安装说明… 📖")
        page = browser.read_url(item["url"])
        if page.get("protected_event") or not page.get("success"):
            continue
        pages.append(
            {
                "id": item["id"],
                "title": item["title"],
                "domain": item["domain"],
                "url": item["url"],
                "content": str(page.get("content") or "")[:16000],
            }
        )
    return pages


def _extract_manifests(message, plan, pages, procedure=None):
    pages_by_id = {page["id"]: page for page in pages}
    manifests = []
    evidence_pages = [
        {
            "source_id": page["id"],
            "title": page["title"],
            "domain": page["domain"],
            "content": page["content"][:5000],
        }
        for page in pages[:MAX_READ]
    ]
    payload = {
        "request": str(message)[:700],
        "research_plan": plan,
        "pages": evidence_pages,
    }
    if isinstance(procedure, dict):
        payload["learned_installation_procedure"] = {
            key: procedure.get(key)
            for key in (
                "target_app",
                "content_kind",
                "expected_file_types",
                "destination_hints",
                "installation_steps",
                "post_install_steps",
                "evidence_summary",
            )
        }
    result = _ai(
        "prompts/casper_content_manifest_extract.txt",
        payload,
        3000,
        num_ctx=16384,
    )
    if not (
        isinstance(result, dict)
        and isinstance(result.get("manifests"), list)
    ):
        result = _ai(
            "prompts/casper_content_manifest_extract_retry.txt",
            {**payload, "previous_invalid_output": result},
            2600,
            num_ctx=16384,
        )
    raw_items = result.get("manifests", []) if isinstance(result, dict) else []
    for raw in raw_items[:8]:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "")
        evidence_page = pages_by_id.get(source_id)
        name = str(raw.get("artifact_name") or "").strip()[:240]
        destination_hints = _strings(raw.get("destination_hints"), 10, 300)
        installation_steps = _strings(raw.get("installation_steps"), 14, 400)
        if (
            not evidence_page
            or not name
            or not destination_hints
            or not installation_steps
        ):
            continue
        supporting_source_ids = []
        for value in raw.get("supporting_source_ids", []):
            candidate = str(value or "").strip()
            if (
                candidate in pages_by_id
                and candidate != source_id
                and candidate not in supporting_source_ids
            ):
                supporting_source_ids.append(candidate)
            if len(supporting_source_ids) >= 6:
                break
        manifests.append(
            {
                "id": _opaque_source_id(source_id + "\0" + name),
                "source_id": source_id,
                "supporting_source_ids": supporting_source_ids,
                "artifact_name": name,
                "target_app": str(raw.get("target_app") or plan["target_app"])[:160],
                "content_kind": str(raw.get("content_kind") or plan["content_kind"])[:100],
                "compatibility": str(raw.get("compatibility") or "")[:500],
                "evidence_summary": str(raw.get("evidence_summary") or "")[:700],
                "expected_file_types": _strings(raw.get("expected_file_types"), 12, 24),
                "destination_hints": destination_hints,
                "installation_steps": installation_steps,
                "post_install_steps": _strings(raw.get("post_install_steps"), 10, 300),
                "source_url": evidence_page["url"],
                "source_title": evidence_page["title"],
                "source_domain": evidence_page["domain"],
            }
        )
    return manifests


def _choose_manifest(message, plan, manifests):
    payload = {
        "request": str(message)[:900],
        "research_plan": plan,
        "manifests": [
            {key: value for key, value in item.items() if key != "source_url"}
            for item in manifests
        ],
    }
    result = _ai(
        "prompts/casper_content_manifest_choose.txt", payload, 1600
    )
    if not isinstance(result, dict):
        payload["retry_instruction"] = (
            "Return only manifest_id and a brief reason in JSON."
        )
        result = _ai(
            "prompts/casper_content_manifest_choose.txt", payload, 1400
        )
    selected_id = (
        str(result.get("manifest_id") or "") if isinstance(result, dict) else ""
    )
    return next((item for item in manifests if item["id"] == selected_id), None)


def execute(message, recent_context, status_callback=None, procedure=None):
    plan = _plan(message, recent_context, procedure=procedure)
    if not plan:
        return _clarify("没有可靠地形成内容搜索计划。")
    plan = _review_queries(message, plan)
    if not plan:
        return _clarify(
            "没有形成通过适配背景隔离检查的搜索词，未执行网页搜索。"
        )
    discovered, protected_event = _discover(plan, status_callback)
    if protected_event:
        protected_result = {
            "success": False,
            "completed": False,
            "needs_clarification": False,
            "protected_event": protected_event,
            "reason": "A research page requires human browser verification.",
        }
        if isinstance(procedure, dict):
            protected_result["resume_skill_id"] = str(
                procedure.get("id") or ""
            )
        return protected_result
    if not discovered:
        return _clarify("没有找到可供阅读的内容或安装教程。")
    ranked = _rank_discovered(message, plan, discovered)
    if not ranked:
        retry_queries = _retry_queries(message, plan, discovered)
        if retry_queries:
            retry_plan = dict(plan)
            retry_plan["queries"] = retry_queries
            retry_discovered, retry_protected = _discover(
                retry_plan, status_callback
            )
            if retry_protected:
                protected_result = {
                    "success": False,
                    "completed": False,
                    "needs_clarification": False,
                    "protected_event": retry_protected,
                    "reason": "A retry page requires human browser verification.",
                }
                if isinstance(procedure, dict):
                    protected_result["resume_skill_id"] = str(
                        procedure.get("id") or ""
                    )
                return protected_result
            ranked = _rank_discovered(message, retry_plan, retry_discovered)
            if ranked:
                plan = retry_plan
    if not ranked:
        return _clarify(
            "搜索结果与目标游戏内容无关，暂时没有足够证据生成安装方案。"
        )
    pages = _read_candidates(ranked, status_callback)
    if not pages:
        return _clarify("找到了候选链接，但没有读取到足够的安装说明。")
    manifests = _extract_manifests(
        message, plan, pages, procedure=procedure
    )
    selected = _choose_manifest(message, plan, manifests) if manifests else None
    if not selected:
        return _clarify("现有证据不足以可靠选择一个内容和安装方案。")
    if isinstance(procedure, dict):
        from . import content_download
        from . import skill_registry

        result = content_download.execute(selected, procedure)
        if (
            result.get("success")
            and result.get("completed")
            and str(procedure.get("status") or "").startswith("pending")
        ):
            candidate = skill_registry.mark_execution_success(
                procedure.get("id"), result, selected
            )
            if not candidate:
                return _clarify(
                    "内容已复制，但没有形成可供用户验证的技能候选；未写入 Skills。"
                )
            return {
                **result,
                "action": "content_installation_awaiting_user_verification",
                "requires_user_verification": True,
                "skill_candidate_id": candidate["id"],
                "installed_action": result.get("action"),
                "target_app": candidate.get("target_app"),
                "original_request": candidate.get("original_request") or message,
                "reason": (
                    "The local action completed, but the skill remains pending "
                    "until the user verifies the result in the target app."
                ),
            }
        if (
            result.get("success")
            and result.get("completed")
            and procedure.get("status") == "verified"
        ):
            skill_registry.record_verified_reuse(procedure.get("id"))
        return result
    return {
        "success": True,
        "completed": False,
        "needs_clarification": False,
        "action": "prepared_content_installation_manifest",
        "manifest": selected,
        "skill_id": (
            str(procedure.get("id") or "") if isinstance(procedure, dict) else ""
        ),
        "candidate_count": len(manifests),
        "reason": "AI selected one evidence-backed installation manifest; downloading is the next supervised phase.",
    }


def _clarify(message):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": message,
        "reason": message,
    }
