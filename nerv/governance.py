"""Durable storage, provenance and policy boundaries for NERV."""

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import sqlite_storage


_LOCK = threading.RLock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def data_directory(base_dir=None):
    if base_dir is not None:
        root = Path(base_dir)
    elif getattr(sys, "frozen", False):
        root = Path(sys.executable).parent
    else:
        root = Path(".")
    path = root / "data" / "nerv"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path, default):
    """Load authoritative state and preserve a rollback-compatible mirror."""

    with _LOCK:
        return sqlite_storage.load_document(
            "nerv",
            sqlite_storage.document_key_for(path),
            path,
            default,
            migration_backup_suffix=(
                sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
            ),
        )


def ensure_json(path, default):
    """Ensure both stores exist without overwriting an existing SQLite row."""

    return load_json(path, default)


def save_json(path, value):
    with _LOCK:
        return sqlite_storage.save_document(
            "nerv",
            sqlite_storage.document_key_for(path),
            path,
            value,
            migration_backup_suffix=(
                sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
            ),
        )


def append_jsonl(path, event):
    record = dict(event) if isinstance(event, dict) else {"event": str(event)}
    record.setdefault("at", now_iso())
    with _LOCK:
        return sqlite_storage.append_event(
            "nerv",
            sqlite_storage.document_key_for(path),
            path,
            record,
            migration_backup_suffix=(
                sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
            ),
        )


def compact_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def quote_is_grounded(quote, direct_user_message):
    quote = compact_text(quote, 500)
    message = compact_text(direct_user_message, 4000)
    return bool(quote and quote.casefold() in message.casefold())
