"""V2 MAGI request router.

This module decides what kind of result the user needs.  It deliberately does
not execute search, read documents, or generate the final reply.
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
}

DEFAULT_PLAN = {
    "response_mode": "LOCAL_ANSWER",
    "needs_search": False,
    "research_depth": "none",
    "source_policy": "local_context",
    "claim_to_verify": None,
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


def _normalize_plan(plan):
    if not isinstance(plan, dict):
        return dict(DEFAULT_PLAN)

    normalized = dict(DEFAULT_PLAN)
    normalized.update(plan)

    if normalized["response_mode"] not in VALID_MODES:
        return dict(DEFAULT_PLAN)

    normalized["needs_search"] = bool(normalized["needs_search"])

    # These are routing invariants, not model preferences.
    if normalized["response_mode"] == "LOCAL_ANSWER":
        normalized["needs_search"] = False
        normalized["research_depth"] = "none"
        normalized["source_policy"] = "local_context"

    if normalized["response_mode"] == "NEWS_FEED":
        normalized["needs_search"] = True
        normalized["research_depth"] = "ranked_feed"
        normalized["source_policy"] = "weighted_news"

    if normalized["response_mode"] == "FACT_LOOKUP":
        normalized["needs_search"] = True
        normalized["research_depth"] = "direct_lookup"
        normalized["source_policy"] = "official_first"

    if normalized["response_mode"] == "CLAIM_CHECK":
        normalized["needs_search"] = True
        normalized["research_depth"] = "3_5_7"
        normalized["source_policy"] = "evidence_verification"

    if not isinstance(normalized.get("claim_to_verify"), str):
        normalized["claim_to_verify"] = None

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
        "prompts/magi_router.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=320,
    )

    plan = _normalize_plan(raw_plan)
    print("[MAGI PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan