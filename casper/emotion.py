"""Persistent, bounded emotional state for Bekki.

Balthasar proposes semantic changes. Python owns validation, decay, limits,
storage, and the final readable mood so a prompt cannot directly rewrite state.
"""

import json
import os
from datetime import datetime, timezone


EMOTION_PATH = os.path.join("data", "emotion.json")

DEFAULT_STATE = {
    "version": 1,
    "valence": 0.35,
    "energy": 0.60,
    "closeness": 0.10,
    "mood": "cheerful",
    "last_user_emotion": "neutral",
    "updated_at": None,
}

VALID_MOODS = {
    "cheerful", "playful", "gentle", "curious", "calm",
    "concerned", "excited", "serious",
}


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, float(value)))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _hours_since(timestamp):
    if not timestamp:
        return 0.0
    try:
        previous = datetime.fromisoformat(timestamp)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - previous
        return max(0.0, elapsed.total_seconds() / 3600)
    except (TypeError, ValueError):
        return 0.0


def _derive_mood(valence, energy):
    if valence <= -0.35 and energy >= 0.55:
        return "concerned"
    if valence <= -0.20:
        return "gentle"
    if energy <= 0.30:
        return "calm"
    if valence >= 0.55 and energy >= 0.65:
        return "excited"
    if energy >= 0.72:
        return "curious"
    return "cheerful"


def _normalize_state(state):
    normalized = dict(DEFAULT_STATE)
    if isinstance(state, dict):
        normalized.update(state)

    normalized["valence"] = _clamp(normalized["valence"], -1.0, 1.0)
    normalized["energy"] = _clamp(normalized["energy"], 0.0, 1.0)
    normalized["closeness"] = _clamp(normalized["closeness"], 0.0, 1.0)
    if normalized.get("mood") not in VALID_MOODS:
        normalized["mood"] = _derive_mood(
            normalized["valence"],
            normalized["energy"],
        )
    return normalized


def _apply_decay(state):
    """Gently return short-term mood toward Bekki's stable baseline."""

    hours = min(_hours_since(state.get("updated_at")), 72.0)
    if hours <= 0:
        return state

    decay = min(0.80, hours * 0.035)
    state["valence"] += (DEFAULT_STATE["valence"] - state["valence"]) * decay
    state["energy"] += (DEFAULT_STATE["energy"] - state["energy"]) * decay
    return _normalize_state(state)


def load_state():
    try:
        with open(EMOTION_PATH, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = dict(DEFAULT_STATE)

    return _apply_decay(_normalize_state(state))


def save_state(state):
    normalized = _normalize_state(state)
    normalized["updated_at"] = _now_iso()
    os.makedirs(os.path.dirname(EMOTION_PATH), exist_ok=True)
    temporary_path = EMOTION_PATH + ".tmp"

    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, EMOTION_PATH)
    return normalized


def apply_balthasar_plan(state, plan):
    """Apply small bounded deltas proposed by Balthasar."""

    state = _apply_decay(_normalize_state(state))
    if not isinstance(plan, dict):
        return save_state(state)

    # Routine neutral messages must not create cumulative emotional drift.
    try:
        intensity = _clamp(plan.get("intensity", 0), 0.0, 1.0)
    except (TypeError, ValueError):
        intensity = 0.0

    preserve_current_mood = (
        plan.get("user_emotion") == "neutral"
        and intensity <= 0.20
    )
    if preserve_current_mood:
        valence_delta = 0.0
        energy_delta = 0.0
        closeness_delta = 0.0
    else:
        # One message may influence mood, but never rewrite it dramatically.
        valence_delta = _clamp(plan.get("valence_delta", 0), -0.12, 0.12)
        energy_delta = _clamp(plan.get("energy_delta", 0), -0.10, 0.10)
        closeness_delta = _clamp(plan.get("closeness_delta", 0), 0.0, 0.015)

    state["valence"] = _clamp(
        state["valence"] + valence_delta,
        -1.0,
        1.0,
    )
    state["energy"] = _clamp(
        state["energy"] + energy_delta,
        0.0,
        1.0,
    )
    state["closeness"] = _clamp(
        state["closeness"] + closeness_delta,
        0.0,
        1.0,
    )
    proposed_mood = str(plan.get("bekki_mood", "")).lower().strip()
    if not preserve_current_mood and proposed_mood in VALID_MOODS:
        state["mood"] = proposed_mood
    state["last_user_emotion"] = str(
        plan.get("user_emotion", "neutral")
    )[:40]
    return save_state(state)


def prompt_context(state):
    state = _normalize_state(state)
    return json.dumps(
        {
            "mood": state["mood"],
            "valence": round(state["valence"], 2),
            "energy": round(state["energy"], 2),
            "closeness": round(state["closeness"], 2),
            "last_user_emotion": state["last_user_emotion"],
        },
        ensure_ascii=False,
        indent=2,
    )