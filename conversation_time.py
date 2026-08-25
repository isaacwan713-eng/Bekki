"""Deterministic timestamp and elapsed-time structure for Bekki chats.

Python measures time.  AI decides how that interval should be expressed in a
natural reply (for example, "刚才", "三天前", or "上周").
"""

import json
from datetime import datetime


def now_datetime():
    return datetime.now().astimezone()


def now_iso():
    return now_datetime().isoformat(timespec="seconds")


def parse_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now_datetime().tzinfo)
    return parsed.astimezone()


def normalize_timestamp(value):
    parsed = parse_timestamp(value)
    return parsed.isoformat(timespec="seconds") if parsed else now_iso()


def _seconds(later, earlier):
    return max(0, int((later - earlier).total_seconds()))


def session_time_data(session, limit=8):
    now = now_datetime()
    raw_messages = session.get("messages", []) if isinstance(session, dict) else []
    if not isinstance(raw_messages, list):
        raw_messages = []
    messages = []
    previous_time = None
    for item in raw_messages[-limit:]:
        if not isinstance(item, dict):
            continue
        created = parse_timestamp(item.get("created_at"))
        entry = {
            "role": str(item.get("role", "")),
            "text": str(item.get("text", ""))[:1600],
            "created_at": (
                created.isoformat(timespec="seconds") if created else None
            ),
            "age_seconds_at_request": _seconds(now, created) if created else None,
            "seconds_since_previous_message": (
                _seconds(created, previous_time)
                if created and previous_time else None
            ),
        }
        messages.append(entry)
        if created:
            previous_time = created

    current_time = parse_timestamp(messages[-1].get("created_at")) if messages else now
    previous_message_time = (
        parse_timestamp(messages[-2].get("created_at"))
        if len(messages) >= 2 else None
    )
    return {
        "current_local_time": now.isoformat(timespec="seconds"),
        "current_timezone": str(now.tzinfo),
        "current_message_at": (
            current_time.isoformat(timespec="seconds")
            if current_time else now.isoformat(timespec="seconds")
        ),
        "gap_before_current_message_seconds": (
            _seconds(current_time, previous_message_time)
            if current_time and previous_message_time else None
        ),
        "session_created_at": normalize_timestamp(
            session.get("created_at") if isinstance(session, dict) else None
        ),
        "messages": messages,
    }


def prompt_context(session, limit=8):
    return json.dumps(
        session_time_data(session, limit=limit),
        ensure_ascii=False,
        indent=2,
    )


def recent_conversation(session, limit=8, exclude_last_message=False):
    """Render recent messages, optionally excluding the current saved turn.

    Callers that save the current user message before routing can set
    ``exclude_last_message=True``. The exclusion is structural; Python does not
    interpret the message text.
    """
    requested_limit = max(0, int(limit))
    if requested_limit == 0:
        return ""
    data = session_time_data(
        session,
        limit=requested_limit + (1 if exclude_last_message else 0),
    )
    messages = data["messages"]
    if exclude_last_message and messages:
        messages = messages[:-1]
    messages = messages[-requested_limit:]
    lines = []
    for item in messages:
        timing = (
            "created_at=" + str(item.get("created_at"))
            + "; seconds_since_previous_message="
            + str(item.get("seconds_since_previous_message"))
        )
        lines.append(
            "[" + timing + "] "
            + str(item.get("role", "")) + ": "
            + str(item.get("text", ""))
        )
    return "\n".join(lines)
