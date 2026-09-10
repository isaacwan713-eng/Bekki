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
VALID_COMPANION_MOVES = {
    "direct_answer", "emotional_echo", "playful_tease", "curious_notice",
    "anticipation", "shared_observation", "gentle_disagreement",
}
VALID_COMPANION_CADENCES = {"fragment", "one_sentence", "two_beat"}
VALID_COMPANION_EXPRESSIVENESS = {"low", "medium", "high"}
VALID_COMPANION_FAMILIARITY = {"warm", "familiar", "close"}
VALID_COMPANION_QUESTION_POLICIES = {"none", "rare", "clarify_only"}

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

DEFAULT_COMPANION_PLAN = {
    **DEFAULT_PLAN,
    "social_move": "shared_observation",
    "cadence": "one_sentence",
    "expressiveness": "medium",
    "familiarity": "warm",
    "question_policy": "none",
}

_COMPANION_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "user_emotion": {"type": "string", "enum": sorted(VALID_USER_EMOTIONS)},
        "intensity": {"type": "number", "minimum": 0, "maximum": 1},
        "tone": {"type": "string", "enum": sorted(VALID_TONES)},
        "support_style": {
            "type": "string",
            "enum": sorted(VALID_SUPPORT_STYLES),
        },
        "bekki_mood": {"type": "string", "enum": sorted(VALID_BEKKI_MOODS)},
        "valence_delta": {"type": "number", "minimum": -0.12, "maximum": 0.12},
        "energy_delta": {"type": "number", "minimum": -0.10, "maximum": 0.10},
        "closeness_delta": {"type": "number", "minimum": 0, "maximum": 0.015},
        "social_move": {
            "type": "string",
            "enum": sorted(VALID_COMPANION_MOVES),
        },
        "cadence": {
            "type": "string",
            "enum": sorted(VALID_COMPANION_CADENCES),
        },
        "expressiveness": {
            "type": "string",
            "enum": sorted(VALID_COMPANION_EXPRESSIVENESS),
        },
        "familiarity": {
            "type": "string",
            "enum": sorted(VALID_COMPANION_FAMILIARITY),
        },
        "question_policy": {
            "type": "string",
            "enum": sorted(VALID_COMPANION_QUESTION_POLICIES),
        },
        "reason": {"type": "string", "maxLength": 240},
    },
    "required": [
        "user_emotion", "intensity", "tone", "support_style", "bekki_mood",
        "valence_delta", "energy_delta", "closeness_delta", "social_move",
        "cadence", "expressiveness", "familiarity", "question_policy", "reason",
    ],
    "additionalProperties": False,
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


def _has_valid_plan_contract(plan):
    """Reject schema examples that copied every enum option literally."""
    if not isinstance(plan, dict):
        return False
    return (
        plan.get("user_emotion") in VALID_USER_EMOTIONS
        and plan.get("tone") in VALID_TONES
        and plan.get("support_style") in VALID_SUPPORT_STYLES
        and plan.get("bekki_mood") in VALID_BEKKI_MOODS
    )


def _emotion_state(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _companion_fallback_plan(request_kind, emotion_context, reaction_index=0):
    """Build a zero-latency Balthasar direction for proactive reactions."""

    state = _emotion_state(emotion_context)
    mood = str(state.get("mood") or "cheerful").lower().strip()
    if mood not in VALID_BEKKI_MOODS:
        mood = "cheerful"
    tone = {
        "playful": "playful",
        "excited": "playful",
        "gentle": "warm",
        "concerned": "calm",
        "serious": "serious",
        "calm": "calm",
    }.get(mood, "warm")
    try:
        closeness = max(0.0, min(1.0, float(state.get("closeness", 0))))
    except (TypeError, ValueError):
        closeness = 0.0
    familiarity = "close" if closeness >= 0.65 else (
        "familiar" if closeness >= 0.20 else "warm"
    )
    request_kind = str(request_kind or "").upper().strip()
    if request_kind == "USER_MESSAGE":
        social_move = "direct_answer"
        cadence = "two_beat"
        question_policy = "clarify_only"
    else:
        moves = (
            "shared_observation",
            "emotional_echo",
            "playful_tease",
            "anticipation",
            "curious_notice",
        )
        cadences = ("fragment", "one_sentence", "two_beat")
        try:
            index = max(0, int(reaction_index or 0))
        except (TypeError, ValueError):
            index = 0
        social_move = moves[index % len(moves)]
        cadence = cadences[index % len(cadences)]
        question_policy = "rare" if index % 4 == 3 else "none"
    plan = {
        **DEFAULT_COMPANION_PLAN,
        "tone": tone,
        "bekki_mood": mood,
        "social_move": social_move,
        "cadence": cadence,
        "expressiveness": "high" if mood == "excited" else "medium",
        "familiarity": familiarity,
        "question_policy": question_policy,
        "reason": "Balthasar companion state and turn rotation.",
    }
    return plan


def _normalize_companion_plan(plan, fallback):
    normalized = _normalize_plan(plan)
    for key, allowed in (
        ("social_move", VALID_COMPANION_MOVES),
        ("cadence", VALID_COMPANION_CADENCES),
        ("expressiveness", VALID_COMPANION_EXPRESSIVENESS),
        ("familiarity", VALID_COMPANION_FAMILIARITY),
        ("question_policy", VALID_COMPANION_QUESTION_POLICIES),
    ):
        value = str((plan or {}).get(key) or "").lower().strip()
        normalized[key] = value if value in allowed else fallback[key]
    return normalized


def _has_valid_companion_plan(plan):
    return bool(
        _has_valid_plan_contract(plan)
        and plan.get("social_move") in VALID_COMPANION_MOVES
        and plan.get("cadence") in VALID_COMPANION_CADENCES
        and plan.get("expressiveness") in VALID_COMPANION_EXPRESSIVENESS
        and plan.get("familiarity") in VALID_COMPANION_FAMILIARITY
        and plan.get("question_policy") in VALID_COMPANION_QUESTION_POLICIES
    )


def plan_companion_watch(
    request_kind,
    user_message,
    companion_history,
    emotion_context,
    reaction_index=0,
    model_name="gemma4:12b",
):
    """Direct theater wording without adding a model call to auto reactions."""

    request_kind = str(request_kind or "").upper().strip()
    fallback = _companion_fallback_plan(
        request_kind,
        emotion_context,
        reaction_index=reaction_index,
    )
    if request_kind != "USER_MESSAGE":
        print(
            "[BALTHASAR COMPANION PLAN]",
            json.dumps({**fallback, "source": "state_rotation"}, ensure_ascii=False),
        )
        return fallback

    packet = {
        "request_kind": request_kind,
        "current_user_message": str(user_message or "")[:320],
        "recent_companion_history": companion_history
        if isinstance(companion_history, list) else [],
        "current_bekki_emotional_state": _emotion_state(emotion_context),
        "fallback_delivery": {
            key: fallback[key]
            for key in (
                "tone", "bekki_mood", "social_move", "cadence",
                "expressiveness", "familiarity", "question_policy",
            )
        },
    }
    raw_plan = None
    try:
        raw_plan = tools.run_ai_prompt(
            "prompts/balthasar_companion_watch.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=2048,
            num_predict=320,
            think=False,
            model_name=model_name,
            json_schema=_COMPANION_PLAN_SCHEMA,
        )
    except Exception as error:
        print("[BALTHASAR COMPANION FALLBACK]", repr(error)[:300])
    plan = (
        _normalize_companion_plan(raw_plan, fallback)
        if _has_valid_companion_plan(raw_plan)
        else fallback
    )
    print(
        "[BALTHASAR COMPANION PLAN]",
        json.dumps(
            {
                **plan,
                "source": "ai" if _has_valid_companion_plan(raw_plan) else "fallback",
            },
            ensure_ascii=False,
        ),
    )
    return plan


def plan_response(user_message, conversation_context, emotion_context):
    input_text = (
        "Current Bekki emotional state:\n"
        + emotion_context
        + "\n\nRecent conversation:\n"
        + conversation_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    raw_plan = None
    for prompt_path, model_name, output_budget, context_budget in (
        ("prompts/balthasar_router.txt", "llama3.2:latest", 700, 4096),
        ("prompts/balthasar_router_retry.txt", "gemma4:12b", 1800, 6144),
    ):
        raw_plan = tools.run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=True,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        if _has_valid_plan_contract(raw_plan):
            break
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
    payload = json.dumps(
        {
            "user_message": user_message,
            "melchior_plan": melchior_plan,
            "emotion_plan": emotion_plan,
            "user_context": user_context,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw = None
    for prompt_path, model_name, output_budget, context_budget in (
        ("prompts/balthasar_calibrate.txt", "llama3.2:latest", 700, 4096),
        ("prompts/balthasar_calibrate_retry.txt", "gemma4:12b", 1600, 6144),
    ):
        raw = tools.run_ai_prompt(
            prompt_path,
            payload,
            expect_json=True,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        if isinstance(raw, dict):
            break
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
