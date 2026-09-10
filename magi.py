"""Lightweight, mutually exclusive entry gate for Bekki requests.

MAGI decides only whether the current turn is SEARCH, LOCAL, or COMMAND.
For SEARCH, the same reliable judgment also identifies the requested search
outcome and any explicit named social-platform request. Melchior directly
honors closed recommendation/social contracts and owns remaining detail.
Casper still owns execution.
"""

import json
import re

import media_watch
import source_scope
import tools


VALID_LANES = {"SEARCH", "LOCAL", "COMMAND"}
VALID_SOCIAL_SCOPES = {"SOCIAL_RESEARCH", "OTHER"}
VALID_SOCIAL_PLATFORMS = {
    "bilibili",
    "instagram",
    "reddit",
    "x",
    "xiaohongshu",
    "youtube",
}
VALID_SEARCH_SCOPES = {
    "NEWS_FEED",
    "DISCUSSION_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
    "MEDIA_WATCH",
    "SHOPPING_RESEARCH",
    "RECOMMENDATION_RESEARCH",
    "OTHER",
}
VALID_RECOMMENDATION_DOMAINS = {
    "PRODUCT",
    "RESTAURANT",
    "LOCAL_SERVICE",
    "HEALTHCARE_PROVIDER",
}
VALID_LOCAL_KNOWLEDGE_SUFFICIENCY = {"SUFFICIENT", "PARTIAL", "NONE"}
MIN_ROUTE_CONFIDENCE = 0.65


def _compact(value, maximum):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _valid_ai_route(raw):
    if not isinstance(raw, dict):
        return None
    lane = str(raw.get("lane") or "").upper().strip()
    if lane not in VALID_LANES:
        return None
    try:
        confidence = float(raw.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1:
        return None
    reason = _compact(raw.get("reason"), 220)
    if not reason:
        return None
    # Older persisted test fixtures may omit the V1.3.2 fields. Real model
    # calls use the required schema below. Missing both fields means the
    # legacy non-social contract; a partial or contradictory contract is
    # rejected and receives the normal AI recovery attempt.
    has_social_contract = (
        "social_scope" in raw or "social_platforms" in raw
    )
    if has_social_contract and not (
        "social_scope" in raw and "social_platforms" in raw
    ):
        return None
    social_scope = str(
        raw.get("social_scope") or "OTHER"
    ).upper().strip()
    social_platforms = raw.get("social_platforms", [])
    if social_scope not in VALID_SOCIAL_SCOPES:
        return None
    if not isinstance(social_platforms, list):
        return None
    normalized_platforms = []
    for platform in social_platforms:
        value = str(platform or "").lower().strip()
        if value not in VALID_SOCIAL_PLATFORMS:
            return None
        if value not in normalized_platforms:
            normalized_platforms.append(value)
    if lane == "SEARCH" and social_scope == "SOCIAL_RESEARCH":
        if not normalized_platforms:
            return None
    elif social_scope != "OTHER" or normalized_platforms:
        return None
    has_search_contract = (
        "search_scope" in raw or "recommendation_domain" in raw
    )
    if has_search_contract and not (
        "search_scope" in raw and "recommendation_domain" in raw
    ):
        return None
    if has_search_contract:
        search_scope = str(raw.get("search_scope") or "").upper().strip()
        raw_domain = raw.get("recommendation_domain")
        recommendation_domain = (
            str(raw_domain).upper().strip() if raw_domain is not None else None
        )
    else:
        # Compatibility for older saved tests and in-process recovery objects.
        # All real model calls use the current required closed schema below.
        search_scope = (
            "SOCIAL_RESEARCH"
            if social_scope == "SOCIAL_RESEARCH" else "OTHER"
        )
        recommendation_domain = None
    if search_scope not in VALID_SEARCH_SCOPES:
        return None
    if recommendation_domain is not None and (
        recommendation_domain not in VALID_RECOMMENDATION_DOMAINS
    ):
        return None
    if lane != "SEARCH":
        if search_scope != "OTHER" or recommendation_domain is not None:
            return None
    elif search_scope == "SOCIAL_RESEARCH":
        if social_scope != "SOCIAL_RESEARCH" or recommendation_domain is not None:
            return None
    elif social_scope != "OTHER":
        return None
    elif search_scope == "RECOMMENDATION_RESEARCH":
        if recommendation_domain is None:
            return None
    elif search_scope == "SHOPPING_RESEARCH":
        if recommendation_domain != "PRODUCT":
            return None
    elif recommendation_domain is not None:
        return None
    # Older persisted fixtures may omit this V1.10.19 field. Every real model
    # call receives the required schema below; omission is retained only as a
    # compatibility path and means that no local Knowledge sufficiency was
    # asserted.
    local_knowledge_sufficiency = str(
        raw.get("local_knowledge_sufficiency") or "NONE"
    ).upper().strip()
    if (
        local_knowledge_sufficiency
        not in VALID_LOCAL_KNOWLEDGE_SUFFICIENCY
    ):
        return None
    if lane == "COMMAND" and local_knowledge_sufficiency != "NONE":
        return None
    if lane == "LOCAL" and local_knowledge_sufficiency == "PARTIAL":
        return None
    fixed_sites = source_scope.normalize_domains(raw.get("requested_sites", []))
    normalized_source_scope = str(
        raw.get("source_scope") or source_scope.SOURCE_OPEN_WEB
    ).upper().strip()
    if normalized_source_scope not in source_scope.VALID_SOURCE_SCOPES:
        return None
    if normalized_source_scope == source_scope.SOURCE_FIXED_SITES:
        if lane != "SEARCH" or not fixed_sites:
            return None
    elif fixed_sites:
        return None
    official_only = raw.get("official_only", False)
    if not isinstance(official_only, bool):
        return None
    return {
        "lane": lane,
        "confidence": confidence,
        "reason": reason,
        "social_scope": social_scope,
        "social_platforms": normalized_platforms,
        "search_scope": search_scope,
        "recommendation_domain": recommendation_domain,
        "local_knowledge_sufficiency": local_knowledge_sufficiency,
        "source_scope": normalized_source_scope,
        "requested_sites": fixed_sites,
        "official_only": official_only,
    }


def reconcile_media_watch_route(user_message, route):
    """Repair a model lane conflict for one closed media-discovery contract."""

    if not isinstance(route, dict):
        return route
    if not media_watch.looks_like_media_discovery_request(user_message):
        return route
    if (
        str(route.get("lane") or "").upper().strip() == "SEARCH"
        and str(route.get("search_scope") or "").upper().strip()
        == "MEDIA_WATCH"
        and str(route.get("social_scope") or "OTHER").upper().strip()
        == "OTHER"
        and not route.get("social_platforms")
    ):
        return route
    previous_lane = str(route.get("lane") or "unknown").upper().strip()
    previous_scope = str(
        route.get("search_scope") or "OTHER"
    ).upper().strip()
    repaired = dict(route)
    repaired.update(
        {
            "lane": "SEARCH",
            "social_scope": "OTHER",
            "social_platforms": [],
            "search_scope": "MEDIA_WATCH",
            "recommendation_domain": None,
            "local_knowledge_sufficiency": "NONE",
            "reason": (
                "The requested outcome is to find a concrete or random media "
                "item to watch; any named website is a downstream hard source "
                "condition, not a local device action."
            ),
        }
    )
    if repaired.get("source"):
        repaired["source"] = str(repaired["source"]) + "_watch_contract"
    print(
        "[MAGI MEDIA WATCH CONTRACT]",
        "from=" + previous_lane + "/" + previous_scope,
        "to=SEARCH/MEDIA_WATCH",
    )
    return repaired


def _route_schema():
    return {
        "type": "object",
        "properties": {
            "lane": {"type": "string", "enum": sorted(VALID_LANES)},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
            },
            "reason": {"type": "string"},
            "social_scope": {
                "type": "string",
                "enum": sorted(VALID_SOCIAL_SCOPES),
            },
            "social_platforms": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": sorted(VALID_SOCIAL_PLATFORMS),
                },
                "uniqueItems": True,
                "maxItems": 3,
            },
            "search_scope": {
                "type": "string",
                "enum": sorted(VALID_SEARCH_SCOPES),
            },
            "recommendation_domain": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": sorted(VALID_RECOMMENDATION_DOMAINS),
                    },
                    {"type": "null"},
                ]
            },
            "local_knowledge_sufficiency": {
                "type": "string",
                "enum": sorted(VALID_LOCAL_KNOWLEDGE_SUFFICIENCY),
            },
        },
        "required": [
            "lane",
            "confidence",
            "reason",
            "social_scope",
            "social_platforms",
            "search_scope",
            "recommendation_domain",
            "local_knowledge_sufficiency",
        ],
        "additionalProperties": False,
    }


def _release_router_model(model_name):
    try:
        tools.unload_model(model_name)
        print("[MAGI MODEL RELEASED]", model_name)
    except Exception as error:
        # The next serialized model call also evicts other models.  Explicit
        # release is best-effort and must not discard a valid AI judgment.
        print("[MAGI MODEL RELEASE WARNING]", model_name, repr(error))


def _run_gate(prompt_path, packet, source_prefix):
    # The tested compact model copied prompt examples and produced unrelated
    # lanes for simple Chinese requests. MAGI stays AI-owned, uses the reliable
    # 12B model first, then the installed 4B model for one bounded AI recovery.
    attempts = (
        ("gemma4:12b", 4096, 380),
        ("gemma4:e4b", 4096, 380),
    )
    last_error = None
    previous_raw = None
    for attempt, (model_name, num_ctx, num_predict) in enumerate(attempts):
        attempt_packet = dict(packet)
        if attempt:
            attempt_packet["retry_instruction"] = (
                "The previous AI route was unavailable, invalid, or below the "
                "minimum confidence. Independently classify only the current "
                "message and return one complete JSON object. Classify the "
                "requested answer independently from its named website: one "
                "changing fact from Bilibili, YouTube, or Wikipedia remains "
                "FACT_LOOKUP; only a requested synthesis of platform posts, "
                "videos, comments, or viewpoints is SOCIAL_RESEARCH. When the "
                "answer itself is SOCIAL_RESEARCH, search_scope and "
                "social_scope must both be SOCIAL_RESEARCH and "
                "recommendation_domain must be null. Keep "
                "local_knowledge_sufficiency consistent "
                "with both the active candidate packet and the lane: PARTIAL "
                "cannot choose LOCAL, and COMMAND always uses NONE."
            )
            if isinstance(previous_raw, dict):
                attempt_packet["previous_rejected_route"] = previous_raw
        try:
            raw = tools.run_ai_prompt(
                prompt_path,
                json.dumps(
                    attempt_packet,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                expect_json=True,
                num_ctx=num_ctx,
                num_predict=num_predict,
                think=False,
                model_name=model_name,
                json_schema=_route_schema(),
            )
        except Exception as error:
            last_error = error
            print("[MAGI AI ERROR]", model_name, repr(error))
            continue
        finally:
            _release_router_model(model_name)
        previous_raw = raw
        candidate = reconcile_media_watch_route(
            packet.get("current_user_message"),
            raw,
        )
        media_watch_contract_applied = bool(
            isinstance(raw, dict)
            and isinstance(candidate, dict)
            and (
                str(raw.get("lane") or "").upper().strip()
                != str(candidate.get("lane") or "").upper().strip()
                or str(raw.get("search_scope") or "").upper().strip()
                != str(candidate.get("search_scope") or "").upper().strip()
            )
        )
        candidate = source_scope.reconcile_magi_route(
            packet.get("current_user_message"),
            candidate,
        )
        result = _valid_ai_route(candidate)
        if (
            result
            and not packet.get(
                "active_local_knowledge_candidates_for_current_request"
            )
            and result["local_knowledge_sufficiency"] != "NONE"
        ):
            # This field describes recalled Knowledge only.  Vision evidence,
            # an attached document, or the model's own stable knowledge may
            # still justify the AI-selected LOCAL lane, but none of them can
            # make an empty recalled-Knowledge packet SUFFICIENT or PARTIAL.
            # Canonicalize the mechanically impossible auxiliary value rather
            # than discarding the otherwise valid AI route and spending a
            # second model call on the same routing decision.
            print(
                "[MAGI KNOWLEDGE SUFFICIENCY NORMALIZED]",
                "from=" + result["local_knowledge_sufficiency"],
                "to=NONE",
                "reason=no_candidates",
            )
            result["local_knowledge_sufficiency"] = "NONE"
        if result and result["confidence"] >= MIN_ROUTE_CONFIDENCE:
            result["source"] = (
                source_prefix + "_primary"
                if not attempt
                else source_prefix + "_recovery"
            )
            if media_watch_contract_applied:
                result["source"] += "_watch_contract"
            result = reconcile_media_watch_route(
                packet.get("current_user_message"),
                result,
            )
            print("[MAGI ROUTE]", json.dumps(result, ensure_ascii=False))
            return result
        if result:
            last_error = RuntimeError(
                "MAGI AI confidence was below the route threshold"
            )
            print(
                "[MAGI LOW CONFIDENCE]",
                model_name,
                "confidence=" + str(result["confidence"]),
                "lane=" + result["lane"],
            )
            continue
        last_error = RuntimeError("MAGI AI returned an invalid route contract")
        print("[MAGI INVALID ROUTE]", model_name, repr(raw))
    raise RuntimeError(
        "MAGI could not classify this request after one AI recovery attempt."
    ) from last_error


def route_request(
    user_message,
    recent_context="",
    has_document=False,
    has_image=False,
    nerv_context="",
    image_context="",
    knowledge_context="",
):
    packet = {
        "current_user_message": _compact(user_message, 1200),
        "recent_context_for_reference_only": _compact(recent_context, 900),
        "active_document": bool(has_document),
        "active_image": bool(has_image),
        "active_image_evidence_for_current_request": _compact(
            image_context, 3200
        ),
        "nerv_profile_context_for_reference_only": _compact(
            nerv_context, 700
        ),
        "active_local_knowledge_candidates_for_current_request": _compact(
            knowledge_context, 3000
        ),
    }
    return reconcile_media_watch_route(
        user_message,
        _run_gate("prompts/magi_gate.txt", packet, "ai"),
    )


def audit_route(
    user_message,
    previous_route,
    downstream_mode,
    downstream_reason="",
    recent_context="",
    image_context="",
):
    """Ask reliable MAGI AI to arbitrate one downstream lane disagreement."""
    packet = {
        "current_user_message": _compact(user_message, 1200),
        "previous_magi_route": previous_route,
        "downstream_proposed_mode": _compact(downstream_mode, 80),
        "downstream_reason": _compact(downstream_reason, 260),
        "recent_context_for_reference_only": _compact(recent_context, 500),
        "active_image_evidence_for_current_request": _compact(
            image_context, 3200
        ),
        "audit_instruction": (
            "Re-evaluate independently. Keep or revise the lane based only on "
            "the requested outcome; do not automatically agree with either AI."
        ),
    }
    result = reconcile_media_watch_route(
        user_message,
        _run_gate("prompts/magi_audit.txt", packet, "ai_audit"),
    )
    print("[MAGI AUDIT]", json.dumps(result, ensure_ascii=False))
    return result
