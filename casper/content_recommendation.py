"""AI-selected FM tactic recommendations with exact browser-backed links."""

from . import browser
from . import content_research


MAX_RECOMMENDATIONS = 3


def _recommend(message, plan, pages):
    pages_by_id = {str(page["id"]): page for page in pages}
    payload = {
        "request": str(message)[:900],
        "research_plan": plan,
        "pages": [
            {
                "source_id": page["id"],
                "title": page["title"],
                "domain": page["domain"],
                "content": page["content"][:6500],
            }
            for page in pages[:content_research.MAX_READ]
        ],
    }
    result = content_research._ai(
        "prompts/casper_content_tactic_recommend.txt",
        payload,
        2600,
        num_ctx=16384,
    )
    if not (
        isinstance(result, dict)
        and isinstance(result.get("recommendations"), list)
    ):
        payload["retry_instruction"] = (
            "Return only the compact recommendation JSON using exact source IDs."
        )
        result = content_research._ai(
            "prompts/casper_content_tactic_recommend.txt",
            payload,
            3000,
            num_ctx=16384,
        )
    recommendations = []
    used_source_ids = set()
    raw_items = (
        result.get("recommendations", [])
        if isinstance(result, dict)
        else []
    )
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("source_id") or "")
        page = pages_by_id.get(source_id)
        title = str(raw.get("title") or "").strip()[:180]
        summary = str(raw.get("summary") or "").strip()[:600]
        if (
            not page
            or source_id in used_source_ids
            or not title
            or not summary
        ):
            continue
        used_source_ids.add(source_id)
        recommendations.append(
            {
                "source_id": source_id,
                "title": title,
                "summary": summary,
                "formation": str(raw.get("formation") or "").strip()[:80],
                "fit_reason": str(raw.get("fit_reason") or "").strip()[:300],
                "evidence": str(raw.get("evidence") or "").strip()[:300],
                "url": page["url"],
                "domain": page["domain"],
            }
        )
        if len(recommendations) >= MAX_RECOMMENDATIONS:
            break
    requested_open_id = (
        str(result.get("open_source_id") or "")
        if isinstance(result, dict)
        else ""
    )
    if requested_open_id not in used_source_ids:
        requested_open_id = ""
    return recommendations, requested_open_id


def _cards(recommendations):
    cards = []
    for item in recommendations:
        facts = {}
        if item["formation"]:
            facts["阵型"] = item["formation"]
        if item["evidence"]:
            facts["页面证据"] = item["evidence"]
        sections = []
        if facts:
            sections.append({"kind": "facts", "items": facts})
        if item["fit_reason"]:
            sections.append(
                {
                    "kind": "fit",
                    "label": "适配理由",
                    "text": item["fit_reason"],
                }
            )
        cards.append(
            {
                "type": "article",
                "title": item["title"],
                "summary": item["summary"],
                "url": item["url"],
                "domain": item["domain"],
                "sections": sections,
            }
        )
    return cards


def execute(message, recent_context, status_callback=None):
    plan = content_research._plan(message, recent_context)
    if not plan:
        return _failed("没有可靠地形成战术推荐搜索计划。")
    plan = content_research._review_queries(message, plan)
    if not plan:
        return _failed("战术推荐搜索词没有通过 AI 适配背景隔离检查。")
    discovered, protected = content_research._discover(plan, status_callback)
    if protected:
        return _failed("战术推荐搜索页面需要人工验证。")
    ranked = content_research._rank_discovered(message, plan, discovered)
    if not ranked:
        return _failed("没有找到足够可靠的战术候选来源。")
    pages = content_research._read_candidates(ranked, status_callback)
    recommendations, open_source_id = _recommend(message, plan, pages)
    if not recommendations:
        return _failed("现有网页证据不足以推荐具体战术。")
    page_opened = False
    opened_url = ""
    if open_source_id:
        selected = next(
            item for item in recommendations
            if item["source_id"] == open_source_id
        )
        opened_url = selected["url"]
        try:
            page_opened = bool(browser.open_human_handoff(opened_url))
        except (OSError, RuntimeError, ValueError):
            page_opened = False
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "recommended_fm_tactics",
        "cards": _cards(recommendations),
        "recommendation_count": len(recommendations),
        "tactic_page_opened": page_opened,
        "opened_url": opened_url if page_opened else "",
        "reason": "AI selected browser-evidenced tactic pages; no recommendation was stored as a skill.",
    }


def _failed(message):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": message,
        "reason": message,
        "cards": [],
    }
