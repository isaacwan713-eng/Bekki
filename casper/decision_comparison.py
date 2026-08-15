"""Reusable AI-led option comparison for Bekki.

AI evaluates meaning and trade-offs. Python validates identifiers, score ranges,
field sizes, and ensures unknown evidence cannot silently become a match.
"""

import json


SCORE_FIELDS = {
    "requirement_fit",
    "source_quality",
    "evidence_completeness",
}


def _bounded_score(value):
    try:
        return max(0, min(int(round(float(value))), 100))
    except (TypeError, ValueError):
        return 0


def _short_list(value, maximum=4, item_length=180):
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:item_length] for item in value if str(item).strip()][
        :maximum
    ]


def normalize_comparison(raw, options):
    if not isinstance(raw, dict) or not isinstance(options, list):
        return {"options": [], "recommendation": {}}

    valid_ids = {
        str(option.get("option_id", ""))
        for option in options
        if isinstance(option, dict) and option.get("option_id")
    }
    normalized_options = []
    seen_ids = set()

    for item in raw.get("options", []):
        if not isinstance(item, dict):
            continue
        option_id = str(item.get("option_id", "")).strip()
        if option_id not in valid_ids or option_id in seen_ids:
            continue
        seen_ids.add(option_id)
        normalized = {
            "option_id": option_id,
            "pros": _short_list(item.get("pros")),
            "cons": _short_list(item.get("cons")),
            "best_for": str(item.get("best_for", "")).strip()[:180],
            "caveats": _short_list(item.get("caveats"), maximum=3),
        }
        for field in SCORE_FIELDS:
            normalized[field] = _bounded_score(item.get(field))
        normalized_options.append(normalized)

    recommendation = raw.get("recommendation", {})
    if not isinstance(recommendation, dict):
        recommendation = {}

    def valid_choice(name):
        value = str(recommendation.get(name, "")).strip()
        return value if value in valid_ids else None

    return {
        "options": normalized_options,
        "recommendation": {
            "recommended_option_id": valid_choice("recommended_option_id"),
            "best_value_option_id": valid_choice("best_value_option_id"),
            "best_quality_option_id": valid_choice("best_quality_option_id"),
            "reason": str(recommendation.get("reason", "")).strip()[:500],
            "tradeoffs": _short_list(
                recommendation.get("tradeoffs"), maximum=5, item_length=220
            ),
            "unknowns": _short_list(
                recommendation.get("unknowns"), maximum=5, item_length=220
            ),
        },
    }


def compare_options(options, requirements, ai_runner, preference_profile=None):
    """Ask AI to compare up to three options, then normalize its decision."""
    selected = [item for item in options if isinstance(item, dict)][:3]
    if not selected:
        return {"options": [], "recommendation": {}}

    payload = {
        "requirements": requirements if isinstance(requirements, list) else [],
        "preference_profile": (
            preference_profile if isinstance(preference_profile, dict) else {}
        ),
        "options": selected,
    }
    raw = ai_runner(
        "prompts/decision_compare.txt",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )
    return normalize_comparison(raw, selected)


def prompt_context(comparison, option_titles):
    """Create authoritative comparison context for Bekki's final response."""
    return (
        "DECISION COMPARISON\n"
        "Compare all supplied options; do not describe only the first.\n"
        "Source quality, request fit, and evidence completeness are separate.\n"
        "UNKNOWN evidence is not a match.\n"
        "Option titles:\n"
        + json.dumps(option_titles, ensure_ascii=False, indent=2)
        + "\n\nValidated comparison:\n"
        + json.dumps(comparison, ensure_ascii=False, indent=2)
    )
