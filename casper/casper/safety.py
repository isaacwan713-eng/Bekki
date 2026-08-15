"""Non-negotiable Python safety reflexes for Casper."""


SUPPORTED_MODES = {
    "LOCAL_ANSWER",
    "NEWS_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
    "SHOPPING_RESEARCH",
    "TASK_ACTION",
}

HUMAN_ONLY_EVENTS = {
    "captcha": "CAPTCHA requires human control.",
    "payment": "Final payment requires human confirmation.",
    "permission_escalation": "Permission escalation requires human approval.",
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

