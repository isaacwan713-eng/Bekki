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

DEFAULT_CALIBRATION = {
    "execution_style": "balanced",
    "confirmation_sensitivity": "normal",
    "preferred_sources": [],
    "user_constraints": [],
    "presentation_preferences": [],
    "reason": "No user-specific execution calibration was required.",
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


def _short_list(value, maximum=8):
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:180] for item in value if str(item).strip()][
        :maximum
    ]


def calibrate_execution(
    user_message,
    melchior_plan,
    emotion_plan,
    user_context,
):
    """Calibrate execution without changing Melchior's semantic decision."""
    raw = tools.run_ai_prompt(
        "prompts/balthasar_calibrate.txt",
        json.dumps(
            {
                "user_message": user_message,
                "melchior_plan": melchior_plan,
                "emotion_plan": emotion_plan,
                "user_context": user_context,
            },
            ensure_ascii=False,
            indent=2,
        ),
        expect_json=True,
        num_ctx=4096,
        num_predict=360,
    )
    if not isinstance(raw, dict):
        raw = {}

    calibration = dict(DEFAULT_CALIBRATION)
    style = str(raw.get("execution_style", "balanced")).lower().strip()
    if style in {"fast", "balanced", "thorough"}:
        calibration["execution_style"] = style

    sensitivity = str(
        raw.get("confirmation_sensitivity", "normal")
    ).lower().strip()
    if sensitivity in {"normal", "elevated"}:
        calibration["confirmation_sensitivity"] = sensitivity
    if str(melchior_plan.get("risk", "low")) == "high":
        calibration["confirmation_sensitivity"] = "elevated"

    for field in (
        "preferred_sources",
        "user_constraints",
        "presentation_preferences",
    ):
        calibration[field] = _short_list(raw.get(field))

    calibration["reason"] = str(raw.get("reason", "")).strip()[:280]
    print(
        "[BALTHASAR CALIBRATION]",
        json.dumps(calibration, ensure_ascii=False),
    )
    return calibration
