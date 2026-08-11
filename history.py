# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Persistent local chat sessions for Bekki.

Chat history is intentionally separate from memory.py.  A session stores the
visible bubbles; memory stores only facts Bekki is permitted to remember.
"""

import json
import os
import sys
import uuid
from datetime import datetime


MAX_SESSIONS = 50
MAX_MESSAGES_PER_SESSION = 200
_SOURCE_FIELDS = {
    "domain", "url", "source_score", "is_concrete_news", "content_type",
}


def _history_path():
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.abspath(".")
    )
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "chat_history.json")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _new_session(title="New chat"):
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
    }


def _new_store():
    session = _new_session()
    return {"version": 2, "active_session_id": session["id"], "sessions": [session]}


def _clean_sources(sources):
    if not isinstance(sources, list):
        return []
    return [
        {key: item[key] for key in _SOURCE_FIELDS if key in item}
        for item in sources
        if isinstance(item, dict) and item.get("url")
    ]


def _title_from_text(text):
    title = " ".join(text.split())
    return (title[:28] + "…") if len(title) > 29 else (title or "New chat")


def _migrate_legacy(data):
    """Turn the earlier flat {messages: [...]} file into one session."""
    messages = data.get("messages", []) if isinstance(data, dict) else []
    session = _new_session("New chat")
    session["messages"] = messages[-MAX_MESSAGES_PER_SESSION:] if isinstance(messages, list) else []
    for item in session["messages"]:
        if item.get("role") == "You" and isinstance(item.get("text"), str):
            session["title"] = _title_from_text(item["text"])
            break
    return {
        "version": 2,
        "active_session_id": session["id"],
        "sessions": [session],
        "legacy_context_needs_migration": True,
    }


def _normalise(data):
    if not isinstance(data, dict) or data.get("version") != 2:
        return _migrate_legacy(data if isinstance(data, dict) else {})

    sessions = [item for item in data.get("sessions", []) if isinstance(item, dict) and item.get("id")]
    if not sessions:
        return _new_store()

    for session in sessions:
        session.setdefault("title", "New chat")
        session.setdefault("created_at", _now())
        session.setdefault("updated_at", session["created_at"])
        messages = session.get("messages", [])
        session["messages"] = messages[-MAX_MESSAGES_PER_SESSION:] if isinstance(messages, list) else []

    sessions.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    sessions = sessions[:MAX_SESSIONS]
    active_id = data.get("active_session_id")
    if active_id not in {item["id"] for item in sessions}:
        active_id = sessions[0]["id"]

    normalised = {"version": 2, "active_session_id": active_id, "sessions": sessions}
    if data.get("legacy_context_needs_migration"):
        normalised["legacy_context_needs_migration"] = True
    return normalised


def load_history():
    path = _history_path()
    if not os.path.exists(path):
        return _new_store()
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print("[HISTORY] load failed:", repr(error))
        return _new_store()
    history_data = _normalise(data)
    save_history(history_data)
    return history_data


def save_history(history_data):
    safe_data = _normalise(history_data)
    path = _history_path()
    temporary_path = path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(safe_data, file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    except OSError as error:
        print("[HISTORY] save failed:", repr(error))


def get_active_session(history_data):
    active_id = history_data.get("active_session_id")
    for session in history_data.get("sessions", []):
        if session.get("id") == active_id:
            return session
    return history_data["sessions"][0]


def set_active_session(history_data, session_id):
    if any(item.get("id") == session_id for item in history_data.get("sessions", [])):
        history_data["active_session_id"] = session_id
        save_history(history_data)
        return True
    return False


def create_session(history_data):
    session = _new_session()
    history_data.setdefault("sessions", []).insert(0, session)
    history_data["sessions"] = history_data["sessions"][:MAX_SESSIONS]
    history_data["active_session_id"] = session["id"]
    save_history(history_data)
    return session


def append_message(history_data, role, text, sources=None):
    if role not in {"You", "Bekki"} or not isinstance(text, str):
        return
    session = get_active_session(history_data)
    messages = session.setdefault("messages", [])
    messages.append({
        "role": role,
        "text": text,
        "sources": _clean_sources(sources),
        "created_at": _now(),
    })
    session["messages"] = messages[-MAX_MESSAGES_PER_SESSION:]
    if role == "You" and session.get("title") == "New chat":
        session["title"] = _title_from_text(text)
    session["updated_at"] = _now()
    history_data["sessions"].sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    save_history(history_data)


def clear_active_messages(history_data):
    session = get_active_session(history_data)
    session["messages"] = []
    session["title"] = "New chat"
    session["updated_at"] = _now()
    save_history(history_data)


def delete_session(history_data, session_id):
    """Delete one chat session and always leave at least one session."""
    sessions = history_data.get("sessions", [])
    remaining = [item for item in sessions if item.get("id") != session_id]

    if len(remaining) == len(sessions):
        return False

    if not remaining:
        remaining = [_new_session()]

    history_data["sessions"] = remaining
    if history_data.get("active_session_id") == session_id:
        history_data["active_session_id"] = remaining[0]["id"]

    save_history(history_data)
    return True


def mark_legacy_context_migrated(history_data):
    if history_data.pop("legacy_context_needs_migration", None):
        save_history(history_data)