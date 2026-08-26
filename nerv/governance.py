"""Durable storage, provenance and policy boundaries for NERV."""

import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


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


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def load_json(path, default):
    """Load primary or backup; a malformed generation never becomes state."""
    with _LOCK:
        value = _read_json(path)
        if value is not None:
            return value
        value = _read_json(str(path) + ".bak")
        if value is not None:
            return value
        return default


def _temporary_json(directory, name, value):
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + name + ".", suffix=".tmp", dir=directory, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return temporary


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        primary_tmp = _temporary_json(str(path.parent), path.name, value)
        backup_tmp = None
        try:
            previous = _read_json(path)
            if previous is not None:
                backup_tmp = _temporary_json(
                    str(path.parent), path.name + ".bak", previous
                )
                os.replace(backup_tmp, str(path) + ".bak")
                backup_tmp = None
            os.replace(primary_tmp, path)
            primary_tmp = None
        finally:
            for temporary in (primary_tmp, backup_tmp):
                if temporary:
                    try:
                        os.unlink(temporary)
                    except OSError:
                        pass


def append_jsonl(path, event):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(event) if isinstance(event, dict) else {"event": str(event)}
    record.setdefault("at", now_iso())
    with _LOCK:
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
            os.fsync(file.fileno())


def compact_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def quote_is_grounded(quote, direct_user_message):
    quote = compact_text(quote, 500)
    message = compact_text(direct_user_message, 4000)
    return bool(quote and quote.casefold() in message.casefold())
