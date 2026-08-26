"""Governed ChatGPT Desktop handoff without an OpenAI API or web fallback."""

import json
import re


MAX_OUTBOUND_PROMPT = 5000
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TRAILING_LATIN_PAREN_RE = re.compile(r"\s*[\(（]([^()（）]*[A-Za-z][^()（）]*)[\)）]\s*$")
_TRANSLATION_REQUEST_WORDS = ("翻译", "翻譯", "英文", "英语", "英語", "english")


def _preserve_requested_language(user_message, outbound_prompt):
    """Remove a model-added trailing translation and reject language drift."""
    source = str(user_message or "").strip()
    prompt = str(outbound_prompt or "").strip()
    if not _CJK_RE.search(source):
        return prompt
    source_folded = source.casefold()
    if any(word in source_folded for word in _TRANSLATION_REQUEST_WORDS):
        return prompt
    while True:
        match = _TRAILING_LATIN_PAREN_RE.search(prompt)
        if match is None or match.group(0).strip() in source:
            break
        prompt = prompt[:match.start()].rstrip()
    return prompt if _CJK_RE.search(prompt) else ""


def ask_prompt(outbound_prompt, source_kind="user_explicit"):
    """Send only through ChatGPT Desktop; never open or fall back to web."""
    from . import external_ai_desktop

    return external_ai_desktop.ask_prompt(
        outbound_prompt,
        source_kind=source_kind,
    )


def build_explicit_request(user_message):
    """Use reliable local AI to decide the exact normal-risk outbound prompt."""
    import tools
    from nerv.schemas import EXTERNAL_AI_REQUEST_SCHEMA

    packet = {"current_direct_user_request": str(user_message or "")[:4000]}
    try:
        result = tools.run_ai_prompt(
            "prompts/external_ai_request.txt",
            json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=4096,
            num_predict=650,
            think=False,
            model_name="gemma3:12b",
            json_schema=EXTERNAL_AI_REQUEST_SCHEMA,
        )
    finally:
        try:
            tools.unload_model("gemma3:12b")
            print("[EXTERNAL AI REQUEST MODEL RELEASED] gemma3:12b")
        except Exception as error:
            print("[EXTERNAL AI REQUEST RELEASE WARNING]", repr(error))
    if not isinstance(result, dict):
        return {"decision": "CLARIFY", "reason": "No valid AI decision."}
    decision = str(result.get("decision") or "CLARIFY").upper()
    risk = str(result.get("sharing_risk") or "PROHIBITED").upper()
    prompt = _preserve_requested_language(
        user_message,
        result.get("outbound_prompt"),
    )
    if decision != "SEND" or risk != "NORMAL" or not prompt:
        return {
            "decision": "REFUSE" if risk == "PROHIBITED" else "CLARIFY",
            "sharing_risk": risk,
            "reason": (
                str(result.get("reason") or "")[:500]
                if prompt
                else "The generated question changed the user's requested language."
            ),
        }
    return {
        "decision": "SEND",
        "sharing_risk": "NORMAL",
        "outbound_prompt": prompt[:MAX_OUTBOUND_PROMPT],
        "purpose": str(result.get("purpose") or "")[:300],
        "reason": str(result.get("reason") or "")[:500],
    }


def execute_explicit(user_message, status_callback=None):
    if status_callback:
        status_callback("Bekki 正在整理要问 ChatGPT 的问题…")
    request = build_explicit_request(user_message)
    if request.get("decision") != "SEND":
        return {
            "status": "NEEDS_CLARIFICATION",
            "reason": request.get("reason")
            or "The outbound question was not safe and complete.",
            "sharing_risk": request.get("sharing_risk", "SENSITIVE"),
        }
    if status_callback:
        status_callback("Bekki 正在 ChatGPT Desktop 中询问…")
    return ask_prompt(request["outbound_prompt"], source_kind="user_explicit")
