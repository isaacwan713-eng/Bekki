"""Persistent, bounded appearance preferences for Bekki's desktop UI."""

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path


SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
SETTINGS_FILE = DATA_DIR / "ui_preferences.json"
SUPPORTED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_AVATAR_BYTES = 15 * 1024 * 1024
DEFAULTS = {
    "schema_version": SCHEMA_VERSION,
    "font_family": "Segoe UI Variable",
    "font_size": 13,
    "avatar_path": "",
}


def normalize_preferences(value):
    source = value if isinstance(value, dict) else {}
    result = deepcopy(DEFAULTS)
    family = " ".join(str(source.get("font_family") or "").split())
    if family:
        result["font_family"] = family[:120]
    try:
        size = int(source.get("font_size", DEFAULTS["font_size"]))
    except (TypeError, ValueError):
        size = DEFAULTS["font_size"]
    result["font_size"] = max(11, min(20, size))
    avatar_path = str(source.get("avatar_path") or "").strip()
    result["avatar_path"] = avatar_path[:2000]
    return result


def load_preferences(path=None):
    target = Path(path) if path is not None else SETTINGS_FILE
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        value = {}
    return normalize_preferences(value)


def save_preferences(value, path=None):
    target = Path(path) if path is not None else SETTINGS_FILE
    normalized = normalize_preferences(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return normalized


def persist_avatar(source_path, data_dir=None):
    source = Path(str(source_path or "")).expanduser()
    if not source.is_file():
        raise ValueError("avatar_file_missing")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_AVATAR_EXTENSIONS:
        raise ValueError("avatar_type_not_supported")
    if source.stat().st_size > MAX_AVATAR_BYTES:
        raise ValueError("avatar_file_too_large")
    target_dir = Path(data_dir) if data_dir is not None else DATA_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("bekki_custom_avatar" + suffix)
    if source.resolve() != target.resolve():
        temporary = target.with_name(target.name + ".tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    return str(target.resolve())


def resolved_avatar_path(value, default_path):
    preferences = normalize_preferences(value)
    custom = Path(preferences["avatar_path"]).expanduser()
    if preferences["avatar_path"] and custom.is_file():
        return str(custom)
    return str(default_path)
