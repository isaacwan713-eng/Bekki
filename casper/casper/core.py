"""Casper Core: execute Melchior plans through supervised capabilities."""

from datetime import datetime, timezone

from . import adapters
from .safety import validate_plan


def _base_result(plan):
    mode = str(plan.get("response_mode", "LOCAL_ANSWER"))
    return {
        "status": "completed",
        "action_type": mode.lower(),
        "response_mode": mode,
        "search_result": None,
        "action_context": None,
        "evidence": [],
        "cards": [],
        "artifacts": [],
        "pending_approval": None,
        "errors": [],
        "audit_log": [
            {
                "event": "casper_started",
                "response_mode": mode,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def execute(
    message,
    melchior_plan,
    balthasar_calibration,
    recent_context,
    status_callback,
):
    """Execute one normalized Melchior plan and return a canonical result."""
    result = _base_result(melchior_plan)
    validation = validate_plan(melchior_plan)
    if not validation["allowed"]:
        result["status"] = "safe_stop"
        result["errors"].append(validation["reason"])
        result["audit_log"].append(
            {"event": "casper_safe_stop", "reason": validation["reason"]}
        )
        return result

    try:
        search_result, action_context = adapters.execute_mode(
            message,
            melchior_plan,
            balthasar_calibration,
            recent_context,
            status_callback,
        )
        result["search_result"] = search_result
        result["action_context"] = action_context
        if isinstance(search_result, dict):
            result["evidence"] = search_result.get("results", [])
            result["cards"] = search_result.get("cards", [])
            if search_result.get("status") == "HUMAN_HANDOFF":
                result["status"] = "human_handoff"
                result["pending_approval"] = search_result.get(
                    "pending_approval"
                )
        result["audit_log"].append(
            {
                "event": "casper_completed",
                "status": result["status"],
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as error:
        result["status"] = "failed"
        result["errors"].append(str(error)[:1000])
        result["audit_log"].append(
            {"event": "casper_failed", "error_type": type(error).__name__}
        )
    print(
        "[CASPER RESULT]",
        result["response_mode"],
        result["status"],
        "evidence=" + str(len(result["evidence"])),
        "cards=" + str(len(result["cards"])),
    )
    return result


def execute_pending_search(query, status_callback):
    plan = {
        "response_mode": "CLAIM_CHECK",
        "risk": "low",
        "complexity": "medium",
    }
    result = _base_result(plan)
    try:
        search_result = adapters.execute_pending_search(query, status_callback)
        result["search_result"] = search_result
        if isinstance(search_result, dict):
            result["evidence"] = search_result.get("results", [])
            result["cards"] = search_result.get("cards", [])
    except Exception as error:
        result["status"] = "failed"
        result["errors"].append(str(error)[:1000])
    return result
