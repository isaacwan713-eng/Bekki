# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime


DEFAULT_CONTEXT = {
    "current_topic": None,
    "entities": [],
    "date_context": None,
    "current_goal": None,
    "last_user_intent": None,
    "open_references": {},
}

_active_session_id = None


def _data_dir():
    base_dir = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(".")
    )
    path = base_dir / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _legacy_context_file():
    return _data_dir() / "context.json"


def _context_file():
    if not _active_session_id:
        return _legacy_context_file()
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", _active_session_id)
    path = _data_dir() / "contexts"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{safe_id}.json"


def set_active_session(session_id, migrate_legacy=False):
    """Select the context file belonging to the active chat session."""
    global _active_session_id
    _active_session_id = session_id

    if migrate_legacy and not _context_file().exists():
        legacy = load_legacy_context()
        save_context(legacy)


def load_legacy_context():
    path = _legacy_context_file()
    if not path.exists():
        return DEFAULT_CONTEXT.copy()
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else DEFAULT_CONTEXT.copy()
    except Exception as error:
        print("[CONTEXT LEGACY LOAD ERROR]", error)
        return DEFAULT_CONTEXT.copy()


def load_context():
    path = _context_file()
    if not path.exists():
        return DEFAULT_CONTEXT.copy()
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else DEFAULT_CONTEXT.copy()
    except Exception as error:
        print("[CONTEXT LOAD ERROR]", error)
        return DEFAULT_CONTEXT.copy()


def save_context(context):
    path = _context_file()
    with open(path, "w", encoding="utf-8") as file:
        json.dump(context, file, ensure_ascii=False, indent=2)


def clear_context():
    save_context(DEFAULT_CONTEXT.copy())


def delete_session_context(session_id):
    """Remove the context file belonging to a deleted chat session."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id or "")
    if not safe_id:
        return

    path = _data_dir() / "contexts" / f"{safe_id}.json"
    try:
        if path.exists():
            path.unlink()
    except OSError as error:
        print("[CONTEXT DELETE ERROR]", error)


def update_context(recent_conversation, current_user_message, latest_reply):
    from tools import run_ai_prompt

    previous_context = load_context()
    current_date = datetime.now().date().isoformat()
    input_text = (
        "Current date: " + current_date
        + "\n\nPrevious conversation state:\n"
        + json.dumps(previous_context, ensure_ascii=False, indent=2)
        + "\n\nRecent conversation:\n" + recent_conversation
        + "\n\nCurrent user message:\n" + current_user_message
        + "\n\nBekki's latest reply:\n" + latest_reply
    )

    result = run_ai_prompt(
        "prompts/context.txt", input_text,
        expect_json=True, num_ctx=4096, num_predict=512,
    )
    if not isinstance(result, dict):
        print("[CONTEXT UPDATE FAILED]", result)
        return previous_context

    new_context = {
        "current_topic": result.get("current_topic"),
        "entities": result.get("entities", []),
        "date_context": result.get("date_context"),
        "current_goal": result.get("current_goal"),
        "last_user_intent": result.get("last_user_intent"),
        "open_references": result.get("open_references", {}),
    }
    save_context(new_context)
    print("\n===== CONTEXT STATE =====")
    print(json.dumps(new_context, ensure_ascii=False, indent=2))
    print("=========================\n")
    return new_context