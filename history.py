# Bekki AI
# Created by YW49
"""Persistent local chat sessions, separate from long-term memory."""

import json
import os
import sys
import uuid
from datetime import datetime

MAX_SESSIONS = 50
MAX_MESSAGES_PER_SESSION = 200
_SOURCE_FIELDS = {"domain", "url", "source_score", "is_concrete_news", "content_type"}
_HIGHLIGHT_STYLES = {"important", "warning", "critical", "technical"}

def _history_path():
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.abspath(".")
    folder = os.path.join(base, "data"); os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "chat_history.json")

def _now(): return datetime.now().isoformat(timespec="seconds")

def _new_session(title="New chat"):
    return {"id": uuid.uuid4().hex, "title": title, "created_at": _now(), "updated_at": _now(), "messages": []}

def _new_store():
    session = _new_session()
    return {"version": 3, "active_session_id": session["id"], "sessions": [session]}

def _clean_sources(sources):
    if not isinstance(sources, list): return []
    return [{key:item[key] for key in _SOURCE_FIELDS if key in item} for item in sources if isinstance(item, dict) and item.get("url")]

def _clean_highlights(text, highlights):
    if not isinstance(highlights, list): return []
    clean, seen = [], set()
    for item in highlights[:8]:
        if not isinstance(item, dict): continue
        value, style = str(item.get("text", "")).strip(), str(item.get("style", ""))
        key = (value, style)
        if not value or len(value) > 160 or value not in text or style not in _HIGHLIGHT_STYLES or key in seen: continue
        seen.add(key); clean.append({"text": value, "style": style})
    return clean

def _title_from_text(text):
    title = " ".join(text.split())
    return (title[:28] + "…") if len(title) > 29 else (title or "New chat")

def _normalise(data):
    if not isinstance(data, dict): return _new_store()
    sessions = [x for x in data.get("sessions", []) if isinstance(x, dict) and x.get("id")]
    if not sessions:
        messages = data.get("messages", []) if isinstance(data.get("messages"), list) else []
        session = _new_session(); session["messages"] = messages[-MAX_MESSAGES_PER_SESSION:]
        sessions = [session]
    for session in sessions:
        session.setdefault("title", "New chat"); session.setdefault("created_at", _now()); session.setdefault("updated_at", session["created_at"])
        session["messages"] = session.get("messages", [])[-MAX_MESSAGES_PER_SESSION:] if isinstance(session.get("messages"), list) else []
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True); sessions = sessions[:MAX_SESSIONS]
    active = data.get("active_session_id")
    if active not in {x["id"] for x in sessions}: active = sessions[0]["id"]
    result = {"version": 3, "active_session_id": active, "sessions": sessions}
    if data.get("legacy_context_needs_migration"): result["legacy_context_needs_migration"] = True
    return result

def load_history():
    path = _history_path()
    try:
        with open(path, "r", encoding="utf-8") as file: data = json.load(file)
    except (FileNotFoundError, OSError, json.JSONDecodeError): data = _new_store()
    value = _normalise(data); save_history(value); return value

def save_history(data):
    path = _history_path(); temporary = path + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as file: json.dump(_normalise(data), file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except OSError as error: print("[HISTORY] save failed:", repr(error))

def get_active_session(data):
    return next((x for x in data["sessions"] if x.get("id") == data.get("active_session_id")), data["sessions"][0])

def set_active_session(data, session_id):
    if not any(x.get("id") == session_id for x in data.get("sessions", [])): return False
    data["active_session_id"] = session_id; save_history(data); return True

def create_session(data):
    session = _new_session(); data.setdefault("sessions", []).insert(0, session); data["sessions"] = data["sessions"][:MAX_SESSIONS]; data["active_session_id"] = session["id"]; save_history(data); return session

def append_message(data, role, text, sources=None, highlights=None):
    if role not in {"You", "Bekki"} or not isinstance(text, str): return
    session = get_active_session(data); messages = session.setdefault("messages", [])
    messages.append({"role":role, "text":text, "sources":_clean_sources(sources), "highlights":_clean_highlights(text, highlights), "created_at":_now()})
    session["messages"] = messages[-MAX_MESSAGES_PER_SESSION:]
    if role == "You" and session.get("title") == "New chat": session["title"] = _title_from_text(text)
    session["updated_at"] = _now(); data["sessions"].sort(key=lambda x:x.get("updated_at", ""), reverse=True); save_history(data)

def clear_active_messages(data):
    session = get_active_session(data); session["messages"] = []; session["title"] = "New chat"; session["updated_at"] = _now(); save_history(data)

def delete_session(data, session_id):
    remaining = [x for x in data.get("sessions", []) if x.get("id") != session_id]
    if len(remaining) == len(data.get("sessions", [])): return False
    if not remaining: remaining = [_new_session()]
    data["sessions"] = remaining
    if data.get("active_session_id") == session_id: data["active_session_id"] = remaining[0]["id"]
    save_history(data); return True

def mark_legacy_context_migrated(data):
    if data.pop("legacy_context_needs_migration", None): save_history(data)
