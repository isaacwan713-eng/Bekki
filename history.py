# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Persistent local chat sessions.

Chat history stores visible conversation content.
It remains separate from Bekki's long-term memory.
"""

import json
import os
import sys
import uuid
from datetime import datetime

import result_cards


MAX_SESSIONS = 50
MAX_MESSAGES_PER_SESSION = 200

_SOURCE_FIELDS = {
    "domain",
    "url",
    "source_score",
    "is_concrete_news",
    "content_type",
}

_HIGHLIGHT_STYLES = {
    "important",
    "warning",
    "critical",
    "technical",
}


def _history_path():
    base_dir = (
        os.path.dirname(
            sys.executable
        )
        if getattr(
            sys,
            "frozen",
            False,
        )
        else os.path.abspath(".")
    )

    data_dir = os.path.join(
        base_dir,
        "data",
    )

    os.makedirs(
        data_dir,
        exist_ok=True,
    )

    return os.path.join(
        data_dir,
        "chat_history.json",
    )


def _now():
    return datetime.now().isoformat(
        timespec="seconds"
    )


def _new_session(
    title="New chat",
):
    return {
        "id": uuid.uuid4().hex,
        "title": title,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
    }


def _new_store():
    session = _new_session()

    return {
        "version": 4,
        "active_session_id": (
            session["id"]
        ),
        "sessions": [
            session,
        ],
    }


def _clean_sources(
    sources,
):
    if not isinstance(
        sources,
        list,
    ):
        return []

    cleaned = []

    for item in sources:
        if not isinstance(
            item,
            dict,
        ):
            continue

        if not item.get("url"):
            continue

        cleaned.append(
            {
                key: item[key]
                for key in _SOURCE_FIELDS
                if key in item
            }
        )

    return cleaned


def _clean_highlights(
    text,
    highlights,
):
    if not isinstance(
        text,
        str,
    ):
        return []

    if not isinstance(
        highlights,
        list,
    ):
        return []

    cleaned = []
    seen = set()

    for item in highlights[:8]:
        if not isinstance(
            item,
            dict,
        ):
            continue

        value = str(
            item.get(
                "text",
                "",
            )
        ).strip()

        style = str(
            item.get(
                "style",
                "",
            )
        ).strip()

        key = (
            value,
            style,
        )

        if not value:
            continue

        if len(value) > 160:
            continue

        if value not in text:
            continue

        if style not in (
            _HIGHLIGHT_STYLES
        ):
            continue

        if key in seen:
            continue

        seen.add(key)

        cleaned.append(
            {
                "text": value,
                "style": style,
            }
        )

    return cleaned


def _title_from_text(
    text,
):
    title = " ".join(
        text.split()
    )

    if len(title) > 29:
        return title[:28] + "…"

    return title or "New chat"


def _clean_message(
    message,
):
    if not isinstance(
        message,
        dict,
    ):
        return None

    role = message.get("role")
    text = message.get("text")

    if role not in {
        "You",
        "Bekki",
    }:
        return None

    if not isinstance(
        text,
        str,
    ):
        return None

    return {
        "role": role,
        "text": text,
        "sources": (
            _clean_sources(
                message.get(
                    "sources",
                    [],
                )
            )
        ),
        "highlights": (
            _clean_highlights(
                text,
                message.get(
                    "highlights",
                    [],
                ),
            )
        ),
        "cards": (
            result_cards.clean_cards(
                message.get(
                    "cards",
                    [],
                )
            )
        ),
        "created_at": (
            message.get(
                "created_at"
            )
            or _now()
        ),
    }


def _clean_session(
    session,
):
    if not isinstance(
        session,
        dict,
    ):
        return None

    session_id = str(
        session.get(
            "id",
            "",
        )
    ).strip()

    if not session_id:
        return None

    created_at = (
        session.get(
            "created_at"
        )
        or _now()
    )

    messages = session.get(
        "messages",
        [],
    )

    if not isinstance(
        messages,
        list,
    ):
        messages = []

    cleaned_messages = []

    for message in messages[
        -MAX_MESSAGES_PER_SESSION:
    ]:
        cleaned_message = (
            _clean_message(
                message
            )
        )

        if (
            cleaned_message
            is not None
        ):
            cleaned_messages.append(
                cleaned_message
            )

    return {
        "id": session_id,
        "title": str(
            session.get(
                "title",
                "New chat",
            )
        )[:80],
        "created_at": created_at,
        "updated_at": (
            session.get(
                "updated_at"
            )
            or created_at
        ),
        "messages": (
            cleaned_messages
        ),
    }


def _migrate_flat_history(
    data,
):
    """Migrate the earlier flat message store."""

    messages = (
        data.get(
            "messages",
            [],
        )
        if isinstance(
            data,
            dict,
        )
        else []
    )

    if not isinstance(
        messages,
        list,
    ):
        messages = []

    session = _new_session()

    cleaned_messages = []

    for message in messages[
        -MAX_MESSAGES_PER_SESSION:
    ]:
        cleaned_message = (
            _clean_message(
                message
            )
        )

        if (
            cleaned_message
            is not None
        ):
            cleaned_messages.append(
                cleaned_message
            )

    session["messages"] = (
        cleaned_messages
    )

    for message in cleaned_messages:
        if message.get("role") == "You":
            session["title"] = (
                _title_from_text(
                    message.get(
                        "text",
                        "",
                    )
                )
            )
            break

    return {
        "version": 4,
        "active_session_id": (
            session["id"]
        ),
        "sessions": [
            session,
        ],
        "legacy_context_needs_migration": True,
    }


def _normalise(
    data,
):
    if not isinstance(
        data,
        dict,
    ):
        return _new_store()

    raw_sessions = data.get(
        "sessions",
        [],
    )

    if not isinstance(
        raw_sessions,
        list,
    ):
        raw_sessions = []

    sessions = []

    for session in raw_sessions:
        cleaned_session = (
            _clean_session(
                session
            )
        )

        if (
            cleaned_session
            is not None
        ):
            sessions.append(
                cleaned_session
            )

    # Earlier versions used a single top-level
    # messages array instead of sessions.
    if not sessions:
        return _migrate_flat_history(
            data
        )

    sessions.sort(
        key=lambda item: item.get(
            "updated_at",
            "",
        ),
        reverse=True,
    )

    sessions = sessions[
        :MAX_SESSIONS
    ]

    active_session_id = (
        data.get(
            "active_session_id"
        )
    )

    available_ids = {
        session["id"]
        for session in sessions
    }

    if (
        active_session_id
        not in available_ids
    ):
        active_session_id = (
            sessions[0]["id"]
        )

    result = {
        "version": 4,
        "active_session_id": (
            active_session_id
        ),
        "sessions": sessions,
    }

    if data.get(
        "legacy_context_needs_migration"
    ):
        result[
            "legacy_context_needs_migration"
        ] = True

    return result


def load_history():
    path = _history_path()

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

    except (
        FileNotFoundError,
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(
            "[HISTORY] load fallback:",
            repr(error),
        )

        data = _new_store()

    history_data = _normalise(
        data
    )

    save_history(
        history_data
    )

    return history_data


def save_history(
    history_data,
):
    safe_data = _normalise(
        history_data
    )

    path = _history_path()
    temporary_path = (
        path + ".tmp"
    )

    try:
        with open(
            temporary_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                safe_data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temporary_path,
            path,
        )

    except OSError as error:
        print(
            "[HISTORY] save failed:",
            repr(error),
        )


def get_active_session(
    history_data,
):
    active_session_id = (
        history_data.get(
            "active_session_id"
        )
    )

    for session in history_data.get(
        "sessions",
        [],
    ):
        if (
            session.get("id")
            == active_session_id
        ):
            return session

    sessions = history_data.get(
        "sessions",
        [],
    )

    if sessions:
        return sessions[0]

    session = _new_session()

    history_data["sessions"] = [
        session,
    ]

    history_data[
        "active_session_id"
    ] = session["id"]

    return session


def set_active_session(
    history_data,
    session_id,
):
    exists = any(
        session.get("id")
        == session_id
        for session
        in history_data.get(
            "sessions",
            [],
        )
    )

    if not exists:
        return False

    history_data[
        "active_session_id"
    ] = session_id

    save_history(
        history_data
    )

    return True


def create_session(
    history_data,
):
    session = _new_session()

    history_data.setdefault(
        "sessions",
        [],
    ).insert(
        0,
        session,
    )

    history_data["sessions"] = (
        history_data["sessions"][
            :MAX_SESSIONS
        ]
    )

    history_data[
        "active_session_id"
    ] = session["id"]

    save_history(
        history_data
    )

    return session


def append_message(
    history_data,
    role,
    text,
    sources=None,
    highlights=None,
    cards=None,
):
    if role not in {
        "You",
        "Bekki",
    }:
        return

    if not isinstance(
        text,
        str,
    ):
        return

    session = get_active_session(
        history_data
    )

    messages = session.setdefault(
        "messages",
        [],
    )

    messages.append(
        {
            "role": role,
            "text": text,
            "sources": (
                _clean_sources(
                    sources
                )
            ),
            "highlights": (
                _clean_highlights(
                    text,
                    highlights,
                )
            ),
            "cards": (
                result_cards.clean_cards(
                    cards
                )
            ),
            "created_at": _now(),
        }
    )

    session["messages"] = (
        messages[
            -MAX_MESSAGES_PER_SESSION:
        ]
    )

    if (
        role == "You"
        and session.get("title")
        == "New chat"
    ):
        session["title"] = (
            _title_from_text(
                text
            )
        )

    session["updated_at"] = (
        _now()
    )

    history_data["sessions"].sort(
        key=lambda item: item.get(
            "updated_at",
            "",
        ),
        reverse=True,
    )

    save_history(
        history_data
    )


def clear_active_messages(
    history_data,
):
    session = get_active_session(
        history_data
    )

    session["messages"] = []
    session["title"] = "New chat"
    session["updated_at"] = (
        _now()
    )

    save_history(
        history_data
    )


def delete_session(
    history_data,
    session_id,
):
    sessions = history_data.get(
        "sessions",
        [],
    )

    remaining_sessions = [
        session
        for session in sessions
        if session.get("id")
        != session_id
    ]

    if (
        len(remaining_sessions)
        == len(sessions)
    ):
        return False

    if not remaining_sessions:
        remaining_sessions = [
            _new_session()
        ]

    history_data["sessions"] = (
        remaining_sessions
    )

    if (
        history_data.get(
            "active_session_id"
        )
        == session_id
    ):
        history_data[
            "active_session_id"
        ] = (
            remaining_sessions[0][
                "id"
            ]
        )

    save_history(
        history_data
    )

    return True


def mark_legacy_context_migrated(
    history_data,
):
    if history_data.pop(
        "legacy_context_needs_migration",
        None,
    ):
        save_history(
            history_data
        )
