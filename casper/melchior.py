"""V2 Melchior request router.

Melchior decides what kind of result the user needs and how that request
should be handled. It does not execute searches, read documents, or generate
the final user-facing reply.
"""

import json
from datetime import datetime

import context as context_manager
import document
import memory
import tools
import vision


VALID_MODES = {
    "LOCAL_ANSWER",
    "NEWS_FEED",
    "FACT_LOOKUP",
    "CLAIM_CHECK",
    "SOCIAL_RESEARCH",
    "SHOPPING_RESEARCH",
    "TASK_ACTION",
}

VALID_SOCIAL_PLATFORMS = {
    "xiaohongshu",
    "instagram",
    "x",
}

VALID_RISKS = {
    "low",
    "medium",
    "high",
}

VALID_COMPLEXITIES = {
    "low",
    "medium",
    "high",
}

VALID_REASONING_PROFILES = {
    "quick",
    "standard",
    "analytical",
    "cautious",
}

VALID_RESEARCH_PROFILES = {
    "local_context",
    "weighted_news",
    "official_first",
    "evidence_verification",
    "platform_native",
    "shopping_match",
}

MODE_INVARIANTS = {
    "LOCAL_ANSWER": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
    "NEWS_FEED": {
        "needs_search": True,
        "research_depth": "ranked_feed",
        "source_policy": "weighted_news",
        "research_profile": "weighted_news",
    },
    "FACT_LOOKUP": {
        "needs_search": True,
        "research_depth": "direct_lookup",
        "source_policy": "official_first",
        "research_profile": "official_first",
    },
    "CLAIM_CHECK": {
        "needs_search": True,
        "research_depth": "3_5_7",
        "source_policy": "evidence_verification",
        "research_profile": "evidence_verification",
    },
    "SOCIAL_RESEARCH": {
        "needs_search": True,
        "research_depth": "social_handoff",
        "source_policy": "platform_native",
        "research_profile": "platform_native",
    },
    "SHOPPING_RESEARCH": {
        "needs_search": True,
        "research_depth": "shopping_compare",
        "source_policy": "merchant_results",
        "research_profile": "shopping_match",
    },
    "TASK_ACTION": {
        "needs_search": False,
        "research_depth": "none",
        "source_policy": "local_context",
        "research_profile": "local_context",
    },
}

DEFAULT_PLAN = {
    "response_mode": "LOCAL_ANSWER",
    "needs_search": False,
    "research_depth": "none",
    "source_policy": "local_context",
    "risk": "low",
    "complexity": "low",
    "reasoning_profile": "standard",
    "research_profile": "local_context",
    "claim_to_verify": None,
    "social_platforms": [],
    "reason": "Fallback route: answer from local context when possible.",
}


def _document_context():
    if not document.has_document():
        return "NO DOCUMENT ATTACHED"

    current = document.get_current_document()
    return (
        "An active local document is loaded.\n"
        "File name: " + str(current.get("file_name", ""))
    )


def _image_context():
    if not vision.has_image():
        return "NO IMAGE ATTACHED"

    current = vision.get_current_image()
    return (
        "An active image is loaded.\n"
        "File name: " + str(current.get("file_name", ""))
    )


def _normalize_choice(value, valid_values, fallback):
    normalized = str(value).lower().strip()
    if normalized not in valid_values:
        return fallback
    return normalized


def _normalize_plan(plan):
    if not isinstance(plan, dict):
        return dict(DEFAULT_PLAN)

    normalized = dict(DEFAULT_PLAN)
    normalized.update(plan)

    response_mode = str(normalized.get("response_mode", "")).upper().strip()
    if response_mode not in VALID_MODES:
        return dict(DEFAULT_PLAN)
    normalized["response_mode"] = response_mode

    # Mode behavior remains deterministic so malformed model output cannot
    # accidentally disable required search or select the wrong source policy.
    normalized.update(MODE_INVARIANTS[response_mode])

    normalized["risk"] = _normalize_choice(
        normalized.get("risk"),
        VALID_RISKS,
        DEFAULT_PLAN["risk"],
    )
    normalized["complexity"] = _normalize_choice(
        normalized.get("complexity"),
        VALID_COMPLEXITIES,
        DEFAULT_PLAN["complexity"],
    )
    normalized["reasoning_profile"] = _normalize_choice(
        normalized.get("reasoning_profile"),
        VALID_REASONING_PROFILES,
        DEFAULT_PLAN["reasoning_profile"],
    )

    # research_profile is owned by response_mode during this migration phase.
    # Later MAGI versions may allow persona and research strategy to vary
    # independently after each controller supports that behavior.
    normalized["research_profile"] = MODE_INVARIANTS[response_mode][
        "research_profile"
    ]

    platforms = normalized.get("social_platforms", [])
    if not isinstance(platforms, list):
        platforms = []
    normalized["social_platforms"] = [
        str(platform).lower().strip()
        for platform in platforms
        if str(platform).lower().strip() in VALID_SOCIAL_PLATFORMS
    ]
    normalized["social_platforms"] = list(
        dict.fromkeys(normalized["social_platforms"])
    )

    if not isinstance(normalized.get("claim_to_verify"), str):
        normalized["claim_to_verify"] = None
    elif not normalized["claim_to_verify"].strip():
        normalized["claim_to_verify"] = None
    else:
        normalized["claim_to_verify"] = normalized[
            "claim_to_verify"
        ].strip()[:500]

    normalized["reason"] = str(normalized.get("reason", ""))[:280]
    return normalized


def plan_request(user_message, conversation_context=""):
    """Return a normalized V2 routing plan for one user message."""

    memory_data = memory.initialize_memory()
    state = context_manager.load_context()

    input_text = (
        "Current date:\n"
        + datetime.now().date().isoformat()
        + "\n\nCurrent conversation state:\n"
        + json.dumps(state, ensure_ascii=False, indent=2)
        + "\n\nCurrent long-term memory:\n"
        + memory.get_long_term_context(memory_data)
        + "\n\nCurrent document:\n"
        + _document_context()
        + "\n\nCurrent image:\n"
        + _image_context()
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    raw_plan = tools.run_ai_prompt(
        "prompts/melchior_router.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=420,
    )

    plan = _normalize_plan(raw_plan)
    print("[MELCHIOR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan
