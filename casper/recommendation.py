"""AI-led recommendation research executed through Casper's browser body."""

import json
from datetime import datetime

import decision_comparison
import location
import result_cards
import tools

from . import browser


VALID_DOMAINS = {
    "PRODUCT",
    "RESTAURANT",
    "LOCAL_SERVICE",
    "HEALTHCARE_PROVIDER",
}


def _status(callback, text):
    if callback:
        callback(text)


def _ai(prompt, payload, num_predict=1200):
    return tools.run_ai_prompt(
        prompt,
        json.dumps(payload, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=8192,
        num_predict=num_predict,
    )


def _short_strings(value, maximum, length):
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:length] for item in value if str(item).strip()][
        :maximum
    ]


def _bounded_count(value, fallback=3):
    """Bound an AI-selected count without assigning semantic meaning."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = fallback
    return max(1, min(count, 5))


def _review_queries(user_request, domain, plan, queries):
    """Let a second AI review query quality before Casper executes it."""
    raw = _ai(
        "prompts/recommendation_query_review.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "target_country": plan.get("target_country", ""),
            "query_language": plan.get("query_language", ""),
            "requirements": plan.get("requirements", []),
            "comparison_criteria": plan.get("comparison_criteria", []),
            "preferred_sources": plan.get("preferred_sources", []),
            "proposed_queries": queries,
        },
        700,
    )
    reviewed = _short_strings(
        raw.get("queries") if isinstance(raw, dict) else [],
        4,
        240,
    )
    return reviewed or queries


def _plan(user_request, domain, calibration, recent_context):
    raw = _ai(
        "prompts/recommendation_plan.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "recent_context": recent_context,
            "location_context": location.get_localization_context(),
            "balthasar_calibration": calibration,
        },
        900,
    )
    if not isinstance(raw, dict):
        return None
    queries = _short_strings(raw.get("queries"), 4, 240)
    requirements = _short_strings(raw.get("requirements"), 12, 180)
    criteria = _short_strings(raw.get("comparison_criteria"), 10, 120)
    sources = raw.get("preferred_sources", [])
    if not isinstance(sources, list):
        sources = []
    preferred_sources = []
    for item in sources[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:100]
        domain_name = str(item.get("domain", "")).lower().strip()[:160]
        reason = str(item.get("reason", "")).strip()[:220]
        if name and domain_name:
            preferred_sources.append(
                {"name": name, "domain": domain_name, "reason": reason}
            )
    if not queries:
        return None
    plan = {
        "queries": queries,
        "requirements": requirements,
        "comparison_criteria": criteria,
        "preferred_sources": preferred_sources,
        "location": str(raw.get("location", "")).strip()[:180],
        "target_country": str(raw.get("target_country", "")).strip()[:100],
        "query_language": str(raw.get("query_language", "")).strip()[:80],
        "fallback_languages": _short_strings(
            raw.get("fallback_languages"), 3, 80
        ),
        "source_strategy": str(raw.get("source_strategy", "")).strip()[:300],
        "reason": str(raw.get("reason", "")).strip()[:300],
        "target_option_count": _bounded_count(
            raw.get("target_option_count", 3)
        ),
    }
    plan["queries"] = _review_queries(
        user_request,
        domain,
        plan,
        plan["queries"],
    )
    return plan


def _rank_sources(user_request, domain, plan, candidates):
    """Let AI rank locality and authority; Python only applies its scores."""
    payload = []
    for index, item in enumerate(candidates, start=1):
        payload.append(
            {
                "index": index,
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "domain": item.get("domain", ""),
                "url": item.get("url", ""),
            }
        )
    raw = _ai(
        "prompts/recommendation_source_rank.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "target_location": plan.get("location", ""),
            "target_country": plan.get("target_country", ""),
            "query_language": plan.get("query_language", ""),
            "source_strategy": plan.get("source_strategy", ""),
            "candidates": payload,
        },
        1000,
    )
    scores = raw.get("scores", []) if isinstance(raw, dict) else []
    by_index = {}
    for item in scores if isinstance(scores, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
            score = max(0, min(int(float(item.get("score", 0))), 100))
        except (TypeError, ValueError):
            continue
        by_index[index] = score
    ranked = []
    for index, candidate in enumerate(candidates, start=1):
        enriched = dict(candidate)
        enriched["source_score"] = by_index.get(index, 0)
        ranked.append(enriched)
    ranked.sort(key=lambda item: item.get("source_score", 0), reverse=True)
    return ranked


def _extract_one(user_request, domain, plan, candidate, page):
    raw = _ai(
        "prompts/recommendation_extract.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "plan": plan,
            "candidate": {
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "domain": candidate.get("domain", ""),
                "url": candidate.get("url", ""),
                "source_score": candidate.get("source_score", 50),
            },
            "rendered_page": str(page.get("content", ""))[:18000],
            "page_image_url": page.get("image_url", ""),
        },
        1300,
    )
    if not isinstance(raw, dict) or not raw.get("is_real_candidate"):
        return None
    title = str(raw.get("title", "")).strip()[:180]
    if not title:
        return None
    card_type = {
        "PRODUCT": "article",
        "RESTAURANT": "place",
        "LOCAL_SERVICE": "service",
        "HEALTHCARE_PROVIDER": "provider",
    }[domain]
    return {
        "option_id": "",
        "title": title,
        "summary": str(raw.get("summary", "")).strip()[:600],
        "domain": candidate.get("domain", ""),
        "url": candidate.get("url", ""),
        "source_title": candidate.get("title", ""),
        "image_url": str(raw.get("image_url") or page.get("image_url", "")),
        "card_type": card_type,
        "metadata": raw.get("metadata", {}),
        "requirements": raw.get("requirements", []),
        "sections": raw.get("sections", []),
        "source_score": candidate.get("source_score", 50),
        "evidence_completeness": raw.get("evidence_completeness", 0),
        "unknowns": _short_strings(raw.get("unknowns"), 6, 180),
    }


def _route_page(user_request, domain, candidate, page):
    """Ask AI whether a rendered page is a candidate, a guide, or irrelevant."""
    raw = _ai(
        "prompts/recommendation_page_route.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "candidate": {
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "domain": candidate.get("domain", ""),
                "url": candidate.get("url", ""),
                "source_title": candidate.get("title", ""),
            },
            "rendered_page": str(page.get("content", ""))[:16000],
        },
        700,
    )
    if not isinstance(raw, dict):
        return {"page_role": "OTHER", "candidate_names": []}
    role = str(raw.get("page_role", "OTHER")).upper().strip()
    if role not in {"SINGLE_CANDIDATE", "DISCOVERY_GUIDE", "OTHER"}:
        role = "OTHER"
    names = _short_strings(raw.get("candidate_names"), 8, 140)
    return {
        "page_role": role,
        "candidate_names": names if role == "DISCOVERY_GUIDE" else [],
        "reason": str(raw.get("reason", "")).strip()[:300],
    }


def _extract_guide_candidates(user_request, domain, plan, candidate, page):
    """Let AI preserve useful entities embedded in a guide or directory."""
    raw = _ai(
        "prompts/recommendation_guide_extract.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "plan": plan,
            "guide": {
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "domain": candidate.get("domain", ""),
                "url": candidate.get("url", ""),
                "source_score": candidate.get("source_score", 50),
            },
            "target_option_count": plan.get("target_option_count", 3),
            "rendered_page": str(page.get("content", ""))[:20000],
        },
        2400,
    )
    items = raw.get("candidates", []) if isinstance(raw, dict) else []
    if not isinstance(items, list):
        return []
    output = []
    card_type = {
        "PRODUCT": "article",
        "RESTAURANT": "place",
        "LOCAL_SERVICE": "service",
        "HEALTHCARE_PROVIDER": "provider",
    }[domain]
    for item in items[:plan.get("target_option_count", 3)]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:180]
        summary = str(item.get("summary", "")).strip()[:600]
        if not title or not summary:
            continue
        output.append(
            {
                "option_id": "",
                "title": title,
                "summary": summary,
                "domain": candidate.get("domain", ""),
                "url": candidate.get("url", ""),
                "source_title": candidate.get("title", ""),
                "image_url": str(item.get("image_url", "")).strip(),
                "card_type": card_type,
                "metadata": item.get("metadata", {}),
                "requirements": item.get("requirements", []),
                "sections": item.get("sections", []),
                "source_score": candidate.get("source_score", 50),
                "evidence_completeness": item.get("evidence_completeness", 0),
                "unknowns": _short_strings(item.get("unknowns"), 6, 180),
                "evidence_scope": "COLLECTION_ENTRY",
            }
        )
    return output


def _retry_queries(user_request, domain, plan, extracted, guide_names):
    """Ask AI how to recover when the first evidence pass is insufficient."""
    raw = _ai(
        "prompts/recommendation_retry.txt",
        {
            "domain": domain,
            "user_request": user_request,
            "plan": plan,
            "current_candidates": [
                {
                    "title": item.get("title", ""),
                    "requirements": item.get("requirements", []),
                }
                for item in extracted[:8]
            ],
            "guide_names_seen": guide_names[:12],
            "needed_option_count": plan.get("target_option_count", 3),
        },
        700,
    )
    queries = _short_strings(
        raw.get("queries") if isinstance(raw, dict) else [],
        3,
        240,
    )
    return _review_queries(user_request, domain, plan, queries) if queries else []


def _meets_requirements(option):
    """Apply the AI's requirement verdicts without reinterpreting them."""
    requirements = option.get("requirements", [])
    if not isinstance(requirements, list):
        return True
    return not any(
        isinstance(item, dict)
        and str(item.get("status", "")).upper().strip() == "MISMATCH"
        for item in requirements
    )


def _select_distinct_candidates(user_request, domain, plan, options):
    """Let AI edit the evidence set into distinct, relevant recommendations."""
    if not options:
        return []
    payload = {
            "domain": domain,
            "user_request": user_request,
            "target_option_count": plan.get("target_option_count", 3),
            "requirements": plan.get("requirements", []),
            "comparison_criteria": plan.get("comparison_criteria", []),
            "candidates": [
                {
                    "index": index,
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "source_title": item.get("source_title", ""),
                    "source_domain": item.get("domain", ""),
                    "source_url": item.get("url", ""),
                    "requirements": item.get("requirements", []),
                    "sections": item.get("sections", []),
                    "source_score": item.get("source_score", 0),
                }
                for index, item in enumerate(options, start=1)
            ],
        }
    raw = _ai(
        "prompts/recommendation_candidate_select.txt",
        payload,
        900,
    )
    if not isinstance(raw, dict):
        raw = _ai(
            "prompts/recommendation_candidate_select.txt",
            {**payload, "format_retry": "Return the complete JSON only."},
            900,
        )
    indices = raw.get("selected_indices", []) if isinstance(raw, dict) else []
    selected = []
    seen = set()
    for value in indices if isinstance(indices, list) else []:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index in seen or index < 1 or index > len(options):
            continue
        seen.add(index)
        selected.append(options[index - 1])
        if len(selected) >= plan.get("target_option_count", 3):
            break
    return selected


def research_controller(
    user_request,
    domain,
    calibration,
    recent_context="",
    status_callback=None,
):
    domain = str(domain).upper().strip()
    if domain not in VALID_DOMAINS:
        return {"status": "UNSUPPORTED_DOMAIN", "results": [], "cards": []}

    _status(status_callback, "Casper 正在规划推荐标准与可靠来源… 🧭")
    plan = _plan(user_request, domain, calibration, recent_context)
    if not plan:
        return {"status": "PLAN_FAILED", "results": [], "cards": []}

    _status(status_callback, "Casper 正在后台浏览候选页面… 🌐")
    discovered = []
    seen = set()
    discovery_batches = []
    for query in plan["queries"]:
        discovery = browser.discover_web(query, count=6)
        if discovery.get("status") == "HUMAN_HANDOFF":
            return {
                "status": "HUMAN_HANDOFF",
                "pending_approval": {"event": discovery.get("event", "captcha")},
                "results": [],
                "cards": [],
            }
        discovery_batches.append(discovery.get("results", [])[:6])

    # Interleave query results so the first broad query cannot consume the
    # entire evidence budget before alternative strategies are represented.
    for offset in range(6):
        for batch in discovery_batches:
            if offset >= len(batch):
                continue
            item = batch[offset]
            url = item.get("url", "")
            if url and url not in seen:
                seen.add(url)
                discovered.append(item)
            if len(discovered) >= 18:
                break
        if len(discovered) >= 18:
            break

    if not discovered:
        return {"status": "NO_RESULTS", "results": [], "cards": []}

    scored = _rank_sources(user_request, domain, plan, discovered)[:10]
    extracted = []
    guide_names = []
    guide_candidates = []
    seen_titles = set()
    blocked_handoff = None
    for candidate in scored:
        page = browser.read_url(candidate.get("url", ""))
        if page.get("protected_event") in {"captcha", "access_block"}:
            # One blocked source must not erase recommendation evidence already
            # collected from other credible pages.  Remember the handoff and
            # continue; request human help only if no usable cards survive.
            if blocked_handoff is None:
                blocked_handoff = {
                    "event": page.get("protected_event"),
                    "url": candidate.get("url", ""),
                }
            continue
        if not page.get("success"):
            continue
        route = _route_page(user_request, domain, candidate, page)
        print(
            "[CASPER RECOMMENDATION PAGE]",
            route["page_role"],
            candidate.get("domain", ""),
            candidate.get("title", "")[:100],
        )
        if route["page_role"] == "DISCOVERY_GUIDE":
            for name in route["candidate_names"]:
                key = name.casefold()
                if key not in seen_titles:
                    seen_titles.add(key)
                    guide_names.append(name)
            guide_candidates.extend(
                _extract_guide_candidates(
                    user_request, domain, plan, candidate, page
                )
            )
            continue
        if route["page_role"] != "SINGLE_CANDIDATE":
            continue
        option = _extract_one(user_request, domain, plan, candidate, page)
        if option:
            option["option_id"] = "candidate_" + str(len(extracted) + 1)
            extracted.append(option)
        if len(extracted) >= 5:
            break

    # Guides are discovery evidence, not cards. Use AI-selected names from them
    # to discover and read concrete candidate pages before comparison.
    if domain != "PRODUCT" and len(extracted) < 3 and guide_names:
        _status(status_callback, "Casper 正在从指南追踪具体候选页面… 🔎")
        seen_urls = {item.get("url", "") for item in extracted}
        for name in guide_names[:6]:
            follow_query = (
                '"' + name + '" '
                + (plan.get("location") or "")
                + " official reservations menu"
            ).strip()
            discovery = browser.discover_web(follow_query, count=4)
            for candidate in discovery.get("results", [])[:3]:
                url = candidate.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                page = browser.read_url(url)
                if not page.get("success"):
                    continue
                route = _route_page(user_request, domain, candidate, page)
                if route["page_role"] != "SINGLE_CANDIDATE":
                    continue
                option = _extract_one(user_request, domain, plan, candidate, page)
                if not option:
                    continue
                title_key = option["title"].casefold()
                if any(item["title"].casefold() == title_key for item in extracted):
                    continue
                option["option_id"] = "candidate_" + str(len(extracted) + 1)
                extracted.append(option)
                break
            if len(extracted) >= 5:
                break

    # Recommendation entities may exist only inside a credible guide or
    # credible guide or directory. Keep those evidence-bounded candidates when
    # no dedicated page was found. Product recommendation deliberately keeps
    # review/roundup evidence here; concrete merchant pages belong to
    # SHOPPING_RESEARCH.
    target_count = plan.get("target_option_count", 3)
    evidence_limit = min(target_count * 4, 12)
    if len(extracted) < evidence_limit:
        for option in guide_candidates:
            title_key = option["title"].casefold()
            if any(item["title"].casefold() == title_key for item in extracted):
                continue
            option["option_id"] = "candidate_" + str(len(extracted) + 1)
            extracted.append(option)
            if len(extracted) >= evidence_limit:
                break

    # If AI's own requirement verdicts say too few candidates qualify, let AI
    # revise the research strategy once.  Python only bounds and executes the
    # returned queries; it does not choose brands or relax requirements.
    preselected = _select_distinct_candidates(
        user_request,
        domain,
        plan,
        [item for item in extracted if _meets_requirements(item)],
    )
    eligible_count = len(preselected)
    if eligible_count < target_count:
        retry_queries = _retry_queries(
            user_request,
            domain,
            plan,
            extracted,
            guide_names,
        )
        if retry_queries:
            _status(status_callback, "Casper 正在补充符合条件的候选… 🔎")
        retry_discovered = []
        for query in retry_queries:
            discovery = browser.discover_web(query, count=6)
            for item in discovery.get("results", []):
                url = item.get("url", "")
                if url and url not in seen:
                    seen.add(url)
                    retry_discovered.append(item)

        retry_scored = _rank_sources(
            user_request, domain, plan, retry_discovered
        )[:10] if retry_discovered else []
        retry_guides = []
        for candidate in retry_scored:
            page = browser.read_url(candidate.get("url", ""))
            if page.get("protected_event") in {"captcha", "access_block"}:
                if blocked_handoff is None:
                    blocked_handoff = {
                        "event": page.get("protected_event"),
                        "url": candidate.get("url", ""),
                    }
                continue
            if not page.get("success"):
                continue
            route = _route_page(user_request, domain, candidate, page)
            print(
                "[CASPER RECOMMENDATION RETRY]",
                route["page_role"],
                candidate.get("domain", ""),
                candidate.get("title", "")[:100],
            )
            if route["page_role"] == "DISCOVERY_GUIDE":
                retry_guides.extend(
                    _extract_guide_candidates(
                        user_request, domain, plan, candidate, page
                    )
                )
            elif route["page_role"] == "SINGLE_CANDIDATE":
                option = _extract_one(
                    user_request, domain, plan, candidate, page
                )
                if option:
                    extracted.append(option)
            # Candidate diversity is judged after all retry evidence is read.

        for option in retry_guides:
            title_key = option["title"].casefold()
            if any(item["title"].casefold() == title_key for item in extracted):
                continue
            extracted.append(option)
            if len(extracted) >= evidence_limit * 2:
                break

    # A candidate explicitly marked MISMATCH by the evidence AI is not a
    # recommendation card. UNKNOWN remains visible and clearly qualified.
    extracted = _select_distinct_candidates(
        user_request,
        domain,
        plan,
        [item for item in extracted if _meets_requirements(item)],
    )
    for index, item in enumerate(extracted, start=1):
        item["option_id"] = "candidate_" + str(index)

    cards = result_cards.clean_cards(
        [
            {
                "type": item["card_type"],
                "title": item["title"],
                "summary": item["summary"],
                "url": item["url"],
                "domain": item["domain"],
                "image": (
                    {
                        "url": item["image_url"],
                        "alt": item["title"],
                        "source_url": item["url"],
                    }
                    if item["image_url"] else None
                ),
                "metadata": {
                    **(item["metadata"] if isinstance(item["metadata"], dict) else {}),
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                "requirements": item["requirements"],
                "sections": item["sections"],
            }
            for item in extracted
        ]
    )[:5]

    if not cards and blocked_handoff is not None:
        return {
            "status": "HUMAN_HANDOFF",
            "pending_approval": blocked_handoff,
            "results": extracted,
            "cards": [],
        }

    options = []
    for index, (card, evidence) in enumerate(zip(cards, extracted), start=1):
        options.append(
            {
                "option_id": "option_" + str(index),
                "title": card["title"],
                "summary": card["summary"],
                "domain": card["domain"],
                "source_score": evidence["source_score"],
                "metadata": card["metadata"],
                "requirements": card["requirements"],
                "sections": card.get("sections", []),
                "unknowns": evidence["unknowns"],
            }
        )
    comparison = decision_comparison.compare_options(
        options,
        plan["requirements"],
        lambda prompt, input_text: tools.run_ai_prompt(
            prompt,
            input_text,
            expect_json=True,
            num_ctx=8192,
            num_predict=1400,
        ),
        preference_profile={
            "calibration": calibration,
            "domain": domain,
            "criteria": plan["comparison_criteria"],
        },
    )
    context = (
        "melchior response mode: RECOMMENDATION_RESEARCH\n"
        "Recommendation domain: " + domain + "\n"
        "Give the direct verdict first, then explain distinct routes. "
        "Use only verified cards and comparison evidence. Links belong to cards.\n\n"
        "Plan:\n" + json.dumps(plan, ensure_ascii=False, indent=2)
        + "\n\nCards:\n" + json.dumps(cards, ensure_ascii=False, indent=2)
        + "\n\n" + decision_comparison.prompt_context(
            comparison,
            {item["option_id"]: item["title"] for item in options},
        )
    )
    return {
        "status": "OK" if cards else "NO_VERIFIED_CANDIDATES",
        "recommendation_domain": domain,
        "plan": plan,
        "results": extracted,
        "cards": cards,
        "comparison": comparison,
        "context": context,
        "discovery_type": "casper_browser",
    }
