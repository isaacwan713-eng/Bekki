"""AI-owned boundary between a new turn and one active checkpoint."""

import json


ALLOWED_RELATIONS = {"CHECKPOINT_REPLY", "NEW_REQUEST", "AMBIGUOUS"}


def classify(message, pending_action, recent_context=""):
    """Classify semantics; Python only validates the returned closed enum."""
    if not isinstance(pending_action, dict) or not pending_action:
        return "NEW_REQUEST"

    import tools

    approval = pending_action.get("approval_payload")
    approval_summary = {}
    if isinstance(approval, dict):
        for key in (
            "handoff_type",
            "event",
            "verification_kind",
            "target_app",
            "content_kind",
            "destination_name",
        ):
            if key in approval:
                approval_summary[key] = approval.get(key)
    payload = {
        "current_request": str(message)[:700],
        "active_checkpoint": {
            "type": str(pending_action.get("type") or "")[:100],
            "event": str(pending_action.get("event") or "")[:120],
            "original_request": str(
                pending_action.get("original_request") or ""
            )[:900],
            "approval_summary": approval_summary,
        },
        "prior_context": str(recent_context)[-1000:],
    }
    input_text = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    attempts = (
        (
            "prompts/casper_pending_turn_relation.txt",
            "llama3.2:latest",
            120,
            2048,
        ),
        (
            "prompts/casper_pending_turn_relation_retry.txt",
            "gemma3:12b",
            700,
            4096,
        ),
    )
    for prompt_path, model_name, output_budget, context_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in ALLOWED_RELATIONS:
            return value
    return "AMBIGUOUS"
