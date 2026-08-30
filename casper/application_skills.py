"""Local procedural memory for exact installed-application launches."""

from datetime import datetime, timezone
from difflib import SequenceMatcher
import glob
import json
import os
import re
import tempfile


_SCHEMA_VERSION = 1


def _application_key(value):
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value).casefold())


def _registry_path():
    override = str(os.environ.get("BEKKI_APP_SKILLS_PATH") or "").strip()
    if override:
        return os.path.abspath(override)
    project_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), os.pardir)
    )
    return os.path.join(project_root, "data", "application_skills.json")


def _empty_registry():
    return {
        "schema_version": _SCHEMA_VERSION,
        "applications": {},
        "steam_games": {},
    }


def _load_registry():
    path = _registry_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return _empty_registry()
    if not isinstance(payload, dict):
        return _empty_registry()
    applications = payload.get("applications")
    steam_games = payload.get("steam_games")
    if not isinstance(applications, dict):
        applications = {}
    if not isinstance(steam_games, dict):
        steam_games = {}
    return {
        "schema_version": _SCHEMA_VERSION,
        "applications": applications,
        "steam_games": steam_games,
    }


def _save_registry(payload):
    path = _registry_path()
    parent = os.path.dirname(path)
    temporary_path = ""
    try:
        os.makedirs(parent, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix="application_skills_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        return True
    except OSError:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        return False


def get_application(target):
    """Return one learned exact identity; never perform fuzzy substitution."""
    requested_key = _application_key(target)
    if not requested_key:
        return None
    applications = _load_registry()["applications"]
    direct = applications.get(requested_key)
    if isinstance(direct, dict):
        return dict(direct)
    for entry in applications.values():
        if not isinstance(entry, dict):
            continue
        aliases = entry.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        candidate_keys = {
            _application_key(entry.get("name")),
            *(_application_key(alias) for alias in aliases),
        }
        if requested_key in candidate_keys:
            return dict(entry)
    return None


def remember_application(
    target,
    *,
    name,
    app_id="",
    shortcut_path="",
    launch_route="",
):
    """Atomically learn or refresh one verified local application procedure."""
    canonical_name = str(name or target or "").strip()
    key = _application_key(canonical_name)
    if not key:
        return False
    payload = _load_registry()
    applications = payload["applications"]
    existing = applications.get(key)
    if not isinstance(existing, dict):
        existing = {}
    aliases = existing.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    for alias in (target, canonical_name):
        text = str(alias or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {
        "name": canonical_name,
        "aliases": aliases[:20],
        "app_id": str(app_id or existing.get("app_id") or "").strip(),
        "shortcut_path": str(
            shortcut_path or existing.get("shortcut_path") or ""
        ).strip(),
        "last_launch_route": str(launch_route or "").strip(),
        "learned_at": str(existing.get("learned_at") or now),
        "last_used_at": now,
    }
    applications[key] = entry
    return _save_registry(payload)


def get_steam_game(target):
    """Return one learned Steam game identity by exact saved alias."""
    requested_key = _application_key(target)
    if not requested_key:
        return None
    games = _load_registry()["steam_games"]
    direct = games.get(requested_key)
    if isinstance(direct, dict):
        return dict(direct)
    for entry in games.values():
        if not isinstance(entry, dict):
            continue
        aliases = entry.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        candidate_keys = {
            _application_key(entry.get("name")),
            *(_application_key(alias) for alias in aliases),
        }
        if requested_key in candidate_keys:
            return dict(entry)
    return None


def remember_steam_game(target, *, name, app_id, launch_route=""):
    """Atomically learn one Steam game alias and its numeric AppID."""
    canonical_name = str(name or target or "").strip()
    game_id = str(app_id or "").strip()
    key = _application_key(canonical_name)
    if not key or not game_id.isdigit():
        return False
    payload = _load_registry()
    games = payload["steam_games"]
    existing = games.get(key)
    if not isinstance(existing, dict):
        existing = {}
    aliases = existing.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    for alias in (target, canonical_name):
        text = str(alias or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    games[key] = {
        "name": canonical_name,
        "aliases": aliases[:20],
        "app_id": game_id,
        "last_launch_route": str(launch_route or "").strip(),
        "learned_at": str(existing.get("learned_at") or now),
        "last_used_at": now,
    }
    return _save_registry(payload)


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _vdf_value(text, key):
    match = re.search(
        r'"' + re.escape(str(key)) + r'"\s+"([^"]*)"',
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _steam_root_candidates():
    roots = []
    if os.name == "nt":
        try:
            import winreg

            for value_name in ("SteamPath", "InstallPath"):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Valve\Steam",
                    ) as key:
                        value, _kind = winreg.QueryValueEx(key, value_name)
                    if str(value or "").strip():
                        roots.append(str(value).strip())
                except OSError:
                    continue
        except (ImportError, OSError):
            pass
    program_files_x86 = str(os.environ.get("ProgramFiles(x86)") or "").strip()
    program_files = str(os.environ.get("ProgramFiles") or "").strip()
    for parent in (program_files_x86, program_files):
        if parent:
            roots.append(os.path.join(parent, "Steam"))
    unique = []
    seen = set()
    for root in roots:
        normalized = os.path.normcase(os.path.abspath(root))
        if normalized not in seen:
            seen.add(normalized)
            unique.append(root)
    return unique


def discover_steam_games():
    """Read only installed Steam manifests from local library folders."""
    if os.name != "nt":
        return []
    libraries = []
    for steam_root in _steam_root_candidates():
        steamapps = os.path.join(steam_root, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        libraries.append(steamapps)
        folders_text = _read_text(os.path.join(steamapps, "libraryfolders.vdf"))
        for raw_path in re.findall(
            r'"path"\s+"([^"]+)"', folders_text, flags=re.IGNORECASE
        ):
            library_root = raw_path.replace(r"\\", "\\")
            candidate = os.path.join(library_root, "steamapps")
            if os.path.isdir(candidate):
                libraries.append(candidate)
    unique_libraries = []
    seen_libraries = set()
    for library in libraries:
        key = os.path.normcase(os.path.abspath(library))
        if key not in seen_libraries:
            seen_libraries.add(key)
            unique_libraries.append(library)
    games = []
    seen_ids = set()
    for steamapps in unique_libraries:
        for manifest in glob.glob(os.path.join(steamapps, "appmanifest_*.acf")):
            text = _read_text(manifest)
            app_id = _vdf_value(text, "appid")
            name = _vdf_value(text, "name")
            if not app_id.isdigit() or not name or app_id in seen_ids:
                continue
            seen_ids.add(app_id)
            games.append({"name": name, "app_id": app_id})
    return sorted(games, key=lambda item: item["name"].casefold())


def _candidate_shortlist(target, candidates, limit=100):
    requested = _application_key(target)
    requested_words = set(re.findall(r"[0-9a-z]+", str(target).casefold()))
    ranked = []
    for position, candidate in enumerate(candidates):
        name = str(candidate.get("name") or "").strip()
        if not name:
            continue
        key = _application_key(name)
        words = set(re.findall(r"[0-9a-z]+", name.casefold()))
        score = SequenceMatcher(None, requested, key).ratio()
        score += 1.0 * len(requested_words & words)
        if requested and (requested in key or key in requested):
            score += 2.0
        ranked.append((score, position, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


_CANDIDATE_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_index": {"type": ["integer", "null"]},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "reason": {"type": "string"},
    },
    "required": ["candidate_index", "confidence", "reason"],
    "additionalProperties": False,
}


def _validated_candidate_index(raw, candidate_count):
    """Return (valid_contract, selected_index_or_none)."""
    if not isinstance(raw, dict):
        return False, None
    confidence = str(raw.get("confidence") or "").strip().lower()
    if confidence not in {"high", "low"}:
        return False, None
    selected_value = raw.get("candidate_index")
    if selected_value is None:
        return (confidence == "low"), None
    if isinstance(selected_value, bool):
        return False, None
    try:
        selected_index = int(selected_value)
    except (TypeError, ValueError):
        return False, None
    if not (1 <= selected_index <= int(candidate_count)):
        return False, None
    if confidence != "high":
        return True, None
    return True, selected_index


def select_installed_candidate(target, candidates, candidate_type):
    """Let AI resolve an alias only within a Python-supplied allowlist."""
    shortlist = _candidate_shortlist(target, candidates)
    if not shortlist:
        return None
    candidate_rows = [
        {"candidate_index": index, "name": item.get("name")}
        for index, item in enumerate(shortlist, start=1)
    ]
    input_text = json.dumps(
        {
            "requested_name": str(target),
            "candidate_type": str(candidate_type),
            "candidates": candidate_rows,
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        import tools

        raw = tools.run_ai_prompt(
            "prompts/casper_installed_candidate_select.txt",
            input_text,
            expect_json=True,
            num_ctx=4096,
            num_predict=500,
            think=False,
            model_name="llama3.2:latest",
            json_schema=_CANDIDATE_DECISION_SCHEMA,
        )
    except Exception as error:
        print("[CASPER INSTALLED CANDIDATE AI ERROR]", repr(error))
        raw = None
    valid_contract, selected_index = _validated_candidate_index(
        raw,
        len(shortlist),
    )
    if not valid_contract:
        print("[CASPER INSTALLED CANDIDATE AI RETRY] gemma4:12b")
        try:
            tools.unload_model("llama3.2:latest")
        except Exception as unload_error:
            print(
                "[CASPER INSTALLED CANDIDATE UNLOAD ERROR]",
                repr(unload_error),
            )
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_installed_candidate_select_recover.txt",
                input_text,
                expect_json=True,
                num_ctx=4096,
                num_predict=500,
                think=False,
                model_name="gemma4:12b",
                json_schema=_CANDIDATE_DECISION_SCHEMA,
            )
        except Exception as error:
            print(
                "[CASPER INSTALLED CANDIDATE AI RECOVERY ERROR]",
                repr(error),
            )
            return None
        valid_contract, selected_index = _validated_candidate_index(
            raw,
            len(shortlist),
        )
    if not valid_contract or selected_index is None:
        return None
    selected = shortlist[selected_index - 1]
    print(
        "[CASPER INSTALLED CANDIDATE AI]",
        str(target),
        "->",
        selected.get("name"),
    )
    return selected
