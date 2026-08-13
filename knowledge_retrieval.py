"""Retrieve a small local candidate set, then let AI judge sufficiency."""

import json
import re
from datetime import datetime

import knowledge
import tools


MAX_CANDIDATES = 20
MAX_SELECTED = 5


def _features(text):
    text = str(text).lower()
    latin = set(re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text))
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))
    cjk_pairs = {
        cjk[index:index + 2]
        for index in range(max(0, len(cjk) - 1))
    }
    return latin | cjk_pairs


def shortlist(user_message):
    """Cheap deterministic recall only; this does not decide relevance."""

    query_features = _features(user_message)
    ranked = []
    for item in knowledge.load_active_items():
        text = " ".join(
            [
                str(item.get("subject", "")),
                str(item.get("claim", "")),
                " ".join(str(topic) for topic in item.get("topics", [])),
            ]
        )
        overlap = len(query_features & _features(text))
        if overlap:
            ranked.append((overlap, item))
    ranked.sort(
        key=lambda pair: (
            pair[0],
            float(pair[1].get("confidence", 0)),
            str(pair[1].get("learned_at", "")),
        ),
        reverse=True,
    )
    return [item for _, item in ranked[:MAX_CANDIDATES]]


def judge(user_message, melchior_plan):
    candidates = shortlist(user_message)
    if not candidates:
        return {
            "verdict": "MISSING",
            "selected_ids": [],
            "reason": "No local knowledge candidates were recalled.",
            "evidence": [],
        }

    result = tools.run_ai_prompt(
        "prompts/knowledge_relevance.txt",
        "Current date:\n"
        + datetime.now().date().isoformat()
        + "\n\nCurrent user message:\n"
        + user_message
        + "\n\nMelchior plan:\n"
        + json.dumps(melchior_plan, ensure_ascii=False, indent=2)
        + "\n\nActive local knowledge candidates:\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=6144,
        num_predict=500,
    )
    if not isinstance(result, dict):
        result = {}

    verdict = str(result.get("verdict", "MISSING")).upper()
    if verdict not in {"SUFFICIENT", "PARTIAL", "STALE", "MISSING"}:
        verdict = "MISSING"

    candidate_by_id = {
        str(item.get("id")): item
        for item in candidates
        if item.get("id")
    }
    selected_ids = []
    for item_id in result.get("selected_ids", []):
        item_id = str(item_id)
        if item_id in candidate_by_id and item_id not in selected_ids:
            selected_ids.append(item_id)
        if len(selected_ids) >= MAX_SELECTED:
            break
    evidence = [candidate_by_id[item_id] for item_id in selected_ids]

    if verdict == "SUFFICIENT" and not evidence:
        verdict = "MISSING"

    decision = {
        "verdict": verdict,
        "selected_ids": selected_ids,
        "reason": str(result.get("reason", ""))[:500],
        "evidence": evidence,
    }
    print("[KNOWLEDGE RETRIEVAL]", json.dumps(
        {key: value for key, value in decision.items() if key != "evidence"},
        ensure_ascii=False,
    ))
    return decision


def format_context(decision):
    evidence = decision.get("evidence", [])
    if not evidence:
        return ""
    return (
        "Local Knowledge verdict: "
        + decision.get("verdict", "MISSING")
        + "\nUse only the selected entries below as local knowledge evidence. "
        + "Do not treat them as current if their scope does not match the question.\n"
        + json.dumps(evidence, ensure_ascii=False, indent=2)
    )