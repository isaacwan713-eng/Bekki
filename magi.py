"""Lightweight, mutually exclusive entry gate for Bekki requests.

MAGI decides only whether the current turn is SEARCH, LOCAL, or COMMAND.
For SEARCH, the same reliable judgment also identifies the requested search
outcome and any explicit named social-platform request. Melchior directly
honors closed recommendation/social contracts and owns remaining detail.
Casper still owns execution.
"""

import json
import re

import tools


VALID_LANES = {"SEARCH", "LOCAL", "COMMAND"}
VALID_SOCIAL_SCOPES = {"SOCIAL_RESEARCH", "OTHER"}
VALID_SOCIAL_PLATFORMS = {"xiaohongshu", "instagram", "x"}
VALID_SEARCH_SCOPES = {
    "NEWS_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
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
    return {
        "lane": lane,
        "confidence": confidence,
        "reason": reason,
        "social_scope": social_scope,
        "social_platforms": normalized_platforms,
        "search_scope": search_scope,
        "recommendation_domain": recommendation_domain,
    }


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
        },
        "required": [
            "lane",
            "confidence",
            "reason",
            "social_scope",
            "social_platforms",
            "search_scope",
            "recommendation_domain",
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
        ("gemma3:12b", 3072, 320),
        ("gemma3:4b", 3072, 320),
    )
    last_error = None
    previous_raw = None
    for attempt, (model_name, num_ctx, num_predict) in enumerate(attempts):
        attempt_packet = dict(packet)
        if attempt:
            attempt_packet["retry_instruction"] = (
                "The previous AI route was unavailable, invalid, or below the "
                "minimum confidence. Independently classify only the current "
                "message and return one complete JSON object. Resolve every "
                "closed-contract conflict: when your own judgment sets "
                "social_scope to SOCIAL_RESEARCH, search_scope must also be "
                "SOCIAL_RESEARCH and recommendation_domain must be null, even "
                "when the posts discuss restaurants, products, or other "
                "recommendations."
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
        result = _valid_ai_route(raw)
        if result and result["confidence"] >= MIN_ROUTE_CONFIDENCE:
            result["source"] = (
                source_prefix + "_primary"
                if not attempt
                else source_prefix + "_recovery"
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
):
    packet = {
        "current_user_message": _compact(user_message, 1200),
        "recent_context_for_reference_only": _compact(recent_context, 900),
        "active_document": bool(has_document),
        "active_image": bool(has_image),
    }
    return _run_gate("prompts/magi_gate.txt", packet, "ai")


def audit_route(
    user_message,
    previous_route,
    downstream_mode,
    downstream_reason="",
    recent_context="",
):
    """Ask reliable MAGI AI to arbitrate one downstream lane disagreement."""
    packet = {
        "current_user_message": _compact(user_message, 1200),
        "previous_magi_route": previous_route,
        "downstream_proposed_mode": _compact(downstream_mode, 80),
        "downstream_reason": _compact(downstream_reason, 260),
        "recent_context_for_reference_only": _compact(recent_context, 500),
        "audit_instruction": (
            "Re-evaluate independently. Keep or revise the lane based only on "
            "the requested outcome; do not automatically agree with either AI."
        ),
    }
    result = _run_gate("prompts/magi_audit.txt", packet, "ai_audit")
    print("[MAGI AUDIT]", json.dumps(result, ensure_ascii=False))
    return result
