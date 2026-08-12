"""Balthasar emotional communication router for Bekki."""

import json

import tools


VALID_USER_EMOTIONS = {
    "neutral", "happy", "sad", "frustrated", "anxious",
    "excited", "angry", "tired", "confused", "unwell",
}
VALID_TONES = {"playful", "warm", "calm", "serious"}
VALID_SUPPORT_STYLES = {
    "direct", "encouraging", "comforting", "grounding", "celebrating",
}
VALID_BEKKI_MOODS = {
    "cheerful", "playful", "gentle", "curious", "calm",
    "concerned", "excited", "serious",
}

DEFAULT_PLAN = {
    "user_emotion": "neutral",
    "intensity": 0.0,
    "tone": "warm",
    "support_style": "direct",
    "bekki_mood": "cheerful",
    "valence_delta": 0.0,
    "energy_delta": 0.0,
    "closeness_delta": 0.0,
    "reason": "No strong emotional signal detected.",
}


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_plan(plan):
    if not isinstance(plan, dict):
        return dict(DEFAULT_PLAN)

    normalized = dict(DEFAULT_PLAN)
    normalized.update(plan)

    if normalized.get("user_emotion") not in VALID_USER_EMOTIONS:
        normalized["user_emotion"] = "neutral"
    if normalized.get("tone") not in VALID_TONES:
        normalized["tone"] = "warm"
    if normalized.get("support_style") not in VALID_SUPPORT_STYLES:
        normalized["support_style"] = "direct"
    if normalized.get("bekki_mood") not in VALID_BEKKI_MOODS:
        normalized["bekki_mood"] = "cheerful"

    normalized["intensity"] = max(0.0, min(1.0, _number(normalized["intensity"])))
    normalized["valence_delta"] = max(
        -0.12, min(0.12, _number(normalized["valence_delta"]))
    )
    normalized["energy_delta"] = max(
        -0.10, min(0.10, _number(normalized["energy_delta"]))
    )
    normalized["closeness_delta"] = max(
        0.0, min(0.015, _number(normalized["closeness_delta"]))
    )
    normalized["reason"] = str(normalized.get("reason", ""))[:240]
    return normalized


def plan_response(user_message, conversation_context, emotion_context):
    input_text = (
        "Current Bekki emotional state:\n"
        + emotion_context
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    raw_plan = tools.run_ai_prompt(
        "prompts/balthasar_router.txt",
        input_text,
        expect_json=True,
        num_ctx=3072,
        num_predict=220,
    )
    plan = _normalize_plan(raw_plan)
    print("[BALTHASAR PLAN]", json.dumps(plan, ensure_ascii=False))
    return plan