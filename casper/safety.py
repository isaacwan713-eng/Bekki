"""Non-negotiable Python safety reflexes for Casper."""

import source_scope


SUPPORTED_MODES = {
    "LOCAL_ANSWER",
    "NEWS_FEED",
    "DISCUSSION_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
    "MEDIA_WATCH",
    "SHOPPING_RESEARCH",
    "RECOMMENDATION_RESEARCH",
    "TASK_ACTION",
    "EXTERNAL_AI_ACTION",
    "DEVICE_ACTION",
}

HUMAN_ONLY_EVENTS = {
    "captcha": "CAPTCHA requires human control.",
    "access_block": "Website security verification requires human control.",
    "payment": "Final payment requires human confirmation.",
    "permission_escalation": "Permission escalation requires human approval.",
    "recycle_restore": "Restoring an item from the Recycle Bin requires user confirmation.",
    "credential_request": "Credentials must not be requested through Casper.",
}


def validate_plan(plan):
    if not isinstance(plan, dict):
        return {
            "allowed": False,
            "reason": "Melchior did not provide a valid execution plan.",
        }
    mode = str(plan.get("response_mode", "")).upper().strip()
    if mode not in SUPPORTED_MODES:
        return {
            "allowed": False,
            "reason": "Unsupported Casper response mode: " + mode,
        }
    raw_source_scope = str(
        plan.get("source_scope") or source_scope.SOURCE_OPEN_WEB
    ).upper().strip()
    raw_sites = plan.get("requested_sites", [])
    normalized_sites = source_scope.normalize_domains(raw_sites)
    if raw_source_scope not in source_scope.VALID_SOURCE_SCOPES:
        return {"allowed": False, "reason": "Invalid source-scope contract."}
    if raw_source_scope == source_scope.SOURCE_FIXED_SITES:
        if not isinstance(raw_sites, list) or not normalized_sites:
            return {
                "allowed": False,
                "reason": "FIXED_SITES requires at least one valid public domain.",
            }
        if (
            any(not isinstance(value, str) for value in raw_sites)
            or len(normalized_sites) != len(raw_sites)
        ):
            return {
                "allowed": False,
                "reason": "FIXED_SITES contains an invalid or duplicate domain.",
            }
    elif raw_sites:
        return {
            "allowed": False,
            "reason": "OPEN_WEB cannot carry requested_sites.",
        }
    if not isinstance(plan.get("official_only", False), bool):
        return {"allowed": False, "reason": "official_only must be boolean."}
    return {"allowed": True, "reason": ""}


def reflex(event_type, detail=""):
    """Return an immediate safe-stop result for a protected event."""
    event_type = str(event_type).lower().strip()
    reason = HUMAN_ONLY_EVENTS.get(event_type)
    if reason is None:
        return None
    return {
        "status": "human_handoff",
        "pending_approval": {
            "event": event_type,
            "reason": reason,
            "detail": str(detail)[:500],
        },
    }
