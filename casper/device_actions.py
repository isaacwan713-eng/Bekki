"""Supervised local application launching for Casper.

AI selects semantic intent and one opaque candidate ID. Python owns discovery,
validation and execution, so model output can never become a shell command.
"""

import hashlib
import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


MAX_CANDIDATES = 160
MAX_CONTEXT_CHARS = 2000
MAX_LIBRARY_ITEMS = 100
MAX_LAUNCHER_CONTROLS = 80
MAX_LAUNCH_STRATEGIES = 12
MAX_EXPECTED_EXECUTABLES = 80
SYSTEM_CONTROL_ACTIONS = {
    "VOLUME_UP", "VOLUME_DOWN", "VOLUME_MUTE",
    "MEDIA_PLAY_PAUSE", "MEDIA_NEXT", "MEDIA_PREVIOUS",
    "BRIGHTNESS_UP", "BRIGHTNESS_DOWN",
}
WINDOW_CONTROL_ACTIONS = {
    "FOCUS_WINDOW", "MINIMIZE_WINDOW", "MAXIMIZE_WINDOW", "RESTORE_WINDOW",
}
DEVICE_PLAN_ACTIONS = (
    {"OPEN_APP", "LIST_LIBRARY", "UNSUPPORTED", "CLARIFY"}
    | SYSTEM_CONTROL_ACTIONS
    | WINDOW_CONTROL_ACTIONS
)
AUDIO_SUFFIXES = {
    ".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma",
}


def _local_path(value):
    """Normalize local paths without corrupting Windows drives in tests/tools."""
    value = os.path.expandvars(str(value or ""))
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return os.path.normpath(value)
    return os.path.abspath(value) if value else ""


def _candidate_id(kind, path):
    value = (str(kind) + "\0" + os.path.normcase(str(path))).encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha256(value).hexdigest()[:16]


def _add_candidate(candidates, seen, name, path, kind):
    path = os.path.abspath(os.path.expandvars(str(path)))
    key = os.path.normcase(path)
    if key in seen or not os.path.isfile(path):
        return
    suffix = Path(path).suffix.lower()
    if kind == "shortcut" and suffix != ".lnk":
        return
    if kind == "executable" and suffix != ".exe":
        return
    seen.add(key)
    candidates.append(
        {
            "id": _candidate_id(kind, path),
            "name": str(name).strip()[:120] or Path(path).stem,
            "path": path,
            "kind": kind,
        }
    )


def _resolve_windows_shortcut(path):
    """Resolve one locally discovered .lnk with a fixed PowerShell script."""
    if sys.platform != "win32" or not str(path).lower().endswith(".lnk"):
        return {}
    script = (
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut($env:BEKKI_SHORTCUT_PATH);"
        "@{target=$s.TargetPath;arguments=$s.Arguments;working=$s.WorkingDirectory}"
        "|ConvertTo-Json -Compress"
    )
    environment = os.environ.copy()
    environment["BEKKI_SHORTCUT_PATH"] = str(path)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = json.loads(completed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _bounded_find_file(roots, filename, max_depth=5):
    wanted = str(filename).casefold()
    seen = set()
    for root in roots:
        root = os.path.abspath(str(root)) if root else ""
        root_key = os.path.normcase(root)
        if not root or root_key in seen or not os.path.isdir(root):
            continue
        seen.add(root_key)
        base_depth = len(Path(root).parts)
        for folder, folders, files in os.walk(root):
            depth = len(Path(folder).parts) - base_depth
            if depth >= max_depth:
                folders[:] = []
            for item in files:
                if item.casefold() == wanted:
                    return os.path.join(folder, item)
    return ""


def discover_applications():
    """Return launchable Windows apps without recursively scanning the disk."""
    if sys.platform != "win32":
        return []

    candidates = []
    seen = set()
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
        os.path.join(os.environ.get("PUBLIC", ""), "Desktop"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for folder, _, files in os.walk(root):
            for filename in files:
                if filename.lower().endswith(".lnk"):
                    path = os.path.join(folder, filename)
                    _add_candidate(
                        candidates,
                        seen,
                        Path(filename).stem,
                        path,
                        "shortcut",
                    )
                    if len(candidates) >= MAX_CANDIDATES:
                        break
            if len(candidates) >= MAX_CANDIDATES:
                break
        if len(candidates) >= MAX_CANDIDATES:
            break

    # App Paths contains explicitly registered executables and avoids unsafe
    # filesystem-wide executable discovery.
    try:
        import winreg

        registry_roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for registry_root in registry_roots:
            try:
                with winreg.OpenKey(registry_root, registry_path) as parent:
                    index = 0
                    while len(candidates) < MAX_CANDIDATES:
                        try:
                            child_name = winreg.EnumKey(parent, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(parent, child_name) as child:
                                executable, _ = winreg.QueryValueEx(child, None)
                            _add_candidate(
                                candidates,
                                seen,
                                Path(child_name).stem,
                                executable,
                                "executable",
                            )
                        except OSError:
                            continue
            except OSError:
                continue
    except ImportError:
        pass

    _discover_steam_games(candidates, seen)
    candidates.sort(key=lambda item: item["name"].casefold())
    return candidates[:MAX_CANDIDATES]


def _steam_roots():
    roots = []
    try:
        import winreg

        for registry_path in (
            r"Software\Valve\Steam",
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
                    value, _ = winreg.QueryValueEx(key, "SteamPath")
                    roots.append(str(value))
            except OSError:
                continue
    except ImportError:
        pass
    roots.extend(
        [
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Steam"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Steam"),
        ]
    )
    unique = []
    seen = set()
    for root in roots:
        root = os.path.abspath(os.path.expandvars(root)) if root else ""
        key = os.path.normcase(root)
        if root and key not in seen and os.path.isdir(root):
            seen.add(key)
            unique.append(root)
    return unique


def _acf_value(text, key):
    import re

    match = re.search(
        r'^\s*"' + re.escape(key) + r'"\s+"([^"]*)"',
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _steam_library_roots(steam_root):
    roots = [steam_root]
    library_file = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        text = Path(library_file).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return roots
    import re

    for value in re.findall(r'^\s*"path"\s+"([^"]+)"', text, re.MULTILINE):
        roots.append(value.replace("\\\\", "\\"))
    result = []
    seen = set()
    for root in roots:
        root = os.path.abspath(root)
        key = os.path.normcase(root)
        if key not in seen and os.path.isdir(root):
            seen.add(key)
            result.append(root)
    return result


def _discover_steam_games(candidates, seen):
    """Add installed games from local Steam manifests."""
    for steam_root in _steam_roots():
        for library_root in _steam_library_roots(steam_root):
            steamapps = os.path.join(library_root, "steamapps")
            if not os.path.isdir(steamapps):
                continue
            for manifest in Path(steamapps).glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                app_id = _acf_value(text, "appid")
                name = _acf_value(text, "name")
                if not app_id.isdigit() or not name:
                    continue
                key = "steam:" + app_id
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "id": _candidate_id("steam_game", app_id),
                        "name": name[:120],
                        "kind": "steam_game",
                        "app_id": app_id,
                    }
                )


def _music_roots():
    roots = [
        os.path.join(os.environ.get("USERPROFILE", ""), "Music"),
        os.path.join(os.environ.get("PUBLIC", ""), "Music"),
    ]
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(
                key,
                "{4BD8D571-6D19-48D3-BE97-422220080E43}",
            )
            roots.insert(0, str(value))
    except (ImportError, OSError):
        pass
    result = []
    seen = set()
    for root in roots:
        root = os.path.abspath(os.path.expandvars(root)) if root else ""
        key = os.path.normcase(root)
        if root and key not in seen and os.path.isdir(root):
            seen.add(key)
            result.append(root)
    return result


def list_local_music():
    items = []
    seen = set()
    for root in _music_roots():
        for folder, _, files in os.walk(root):
            for filename in files:
                path = Path(folder, filename)
                if path.suffix.lower() not in AUDIO_SUFFIXES:
                    continue
                key = os.path.normcase(str(path))
                if key in seen:
                    continue
                seen.add(key)
                relative = os.path.relpath(str(path), root)
                items.append(
                    {
                        "title": path.stem[:200],
                        "album_or_folder": str(Path(relative).parent)[:200],
                        "format": path.suffix.lower().lstrip("."),
                    }
                )
                if len(items) >= MAX_LIBRARY_ITEMS:
                    return items
    return items


def list_installed_steam_games(applications):
    games = [
        {"name": item["name"], "app_id": item["app_id"]}
        for item in applications
        if item.get("kind") == "steam_game" and str(item.get("app_id", "")).isdigit()
    ]
    games.sort(key=lambda item: item["name"].casefold())
    return games[:MAX_LIBRARY_ITEMS]


def plan_user_request(message, recent_context, applications=None):
    import tools

    applications = applications if applications is not None else discover_applications()
    applications = list(applications)
    if not any(item.get("kind") == "window" for item in applications):
        applications += discover_windows()
    public_catalog = [
        {"id": item["id"], "name": item["name"], "kind": item["kind"]}
        for item in applications
    ]
    prompt_input = (
        "AVAILABLE APPLICATIONS:\n"
        + json.dumps(public_catalog, ensure_ascii=False, indent=2)
        + "\n\nRECENT CONVERSATION:\n"
        + str(recent_context)[-MAX_CONTEXT_CHARS:]
        + "\n\nCURRENT USER REQUEST:\n"
        + str(message)[:1000]
    )
    raw_plan = tools.run_ai_prompt(
        "prompts/casper_device_action.txt",
        prompt_input,
        # Keep the raw model response so Python can accept either the requested
        # JSON envelope or one exact opaque catalog ID. The latter still comes
        # entirely from AI judgment and is validated against the catalog below.
        expect_json=False,
        num_ctx=8192,
        num_predict=512,
        think=False,
        model_name="llama3.2:latest",
    )
    return raw_plan, applications


def _plan_transport_needs_retry(raw_plan):
    """Detect only an OPEN_APP response cut off inside candidate_id."""
    if not isinstance(raw_plan, str):
        return False
    value = raw_plan.strip()
    # An empty model response is a transport failure, not a semantic NONE.
    # AI still performs the retry selection from the bounded catalog.
    if not value:
        return True
    if not value.startswith("{"):
        return False
    if not re.search(r'"action"\s*:\s*"OPEN_APP"', value, re.IGNORECASE):
        return False
    return bool(
        re.search(
            r'"candidate_id"\s*:\s*"[A-Za-z0-9_-]*$',
            value,
            re.IGNORECASE,
        )
    )


def retry_open_app_selection(message, recent_context, applications):
    """Compact AI retry for any device action after transport truncation."""
    import tools

    catalog = [
        {"id": item["id"], "name": item["name"], "kind": item["kind"]}
        for item in applications
    ]
    prompt_input = (
        "AVAILABLE APPLICATIONS:\n"
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
        + "\nRECENT CONVERSATION:\n"
        + str(recent_context)[-800:]
        + "\nCURRENT USER REQUEST:\n"
        + str(message)[:500]
    )
    return tools.run_ai_prompt(
        "prompts/casper_device_action_retry.txt",
        prompt_input,
        expect_json=True,
        num_ctx=4096,
        num_predict=180,
        think=False,
        model_name="llama3.2:latest",
    )


def select_window_action(message, recent_context, applications):
    """Focused AI selection from visible windows only, never app shortcuts."""
    import tools

    windows = [
        {"id": item["id"], "title": item["name"]}
        for item in applications
        if item.get("kind") == "window"
    ]
    if not windows:
        return None
    raw = tools.run_ai_prompt(
        "prompts/casper_window_action.txt",
        (
            "VISIBLE_WINDOWS:\n"
            + json.dumps(windows, ensure_ascii=False, separators=(",", ":"))
            + "\nRECENT_CONTEXT:\n"
            + str(recent_context)[-600:]
            + "\nCURRENT_REQUEST:\n"
            + str(message)[:500]
        ),
        expect_json=True,
        num_ctx=2048,
        num_predict=100,
        think=False,
        model_name="llama3.2:latest",
    )
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").upper().strip()
    candidate_id = str(raw.get("candidate_id") or "").strip()
    valid_ids = {item["id"] for item in windows}
    if action not in WINDOW_CONTROL_ACTIONS or candidate_id not in valid_ids:
        return None
    return {"action": action, "candidate_id": candidate_id}


def classify_device_action_family(message, recent_context):
    """Let AI separate window control from application launch before targets."""
    try:
        import tools
    except (ImportError, ModuleNotFoundError):
        # The family classifier is an optional AI refinement. A missing
        # integration dependency must not break an otherwise bounded action.
        return ""

    try:
        raw = tools.run_ai_prompt(
            "prompts/casper_device_family.txt",
            (
                "RECENT_CONTEXT:\n"
                + str(recent_context)[-500:]
                + "\nCURRENT_REQUEST:\n"
                + str(message)[:500]
            ),
            expect_json=False,
            num_ctx=1024,
            num_predict=24,
            think=False,
            model_name="llama3.2:latest",
        )
    except (ImportError, ModuleNotFoundError):
        return ""
    value = str(raw or "").strip().upper()
    valid = {
        "OPEN_APPLICATION",
        "WINDOW_CONTROL",
        "SYSTEM_CONTROL",
        "LIST_LIBRARY",
        "FILE_ACTION",
        "RECYCLE_BIN_ACTION",
        "OTHER",
    }
    return value if value in valid else ""


def classify_file_or_library_scope(message, recent_context):
    """Focused AI arbitration among bounded local data scopes."""
    try:
        import tools
    except (ImportError, ModuleNotFoundError):
        return None

    prompt_input = (
        "RECENT_CONTEXT:\n"
        + str(recent_context)[-500:]
        + "\nCURRENT_REQUEST:\n"
        + str(message)[:500]
    )
    for _attempt in range(2):
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_file_or_library.txt",
                prompt_input,
                expect_json=False,
                num_ctx=1024,
                num_predict=16,
                think=False,
                model_name="llama3.2:latest",
            )
        except (ImportError, ModuleNotFoundError):
            return None
        value = str(raw or "").strip().upper()
        if value in {"FILE_ACTION", "LIST_LIBRARY", "RECYCLE_BIN_ACTION"}:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def classify_recycle_bin_scope(message, recent_context):
    """Focused AI gate for Recycle Bin requests mis-shaped as app actions."""
    try:
        import tools
    except (ImportError, ModuleNotFoundError):
        return None
    prompt_input = (
        "RECENT_CONTEXT:\n"
        + str(recent_context)[-400:]
        + "\nCURRENT_REQUEST:\n"
        + str(message)[:500]
    )
    for _attempt in range(2):
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_recycle_scope.txt",
                prompt_input,
                expect_json=False,
                num_ctx=1024,
                num_predict=16,
                think=False,
                model_name="llama3.2:latest",
            )
        except (ImportError, ModuleNotFoundError):
            return None
        value = str(raw or "").strip().upper()
        if value in {"RECYCLE_BIN_ACTION", "OTHER"}:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _normalize_plan(raw_plan, valid_ids):
    """Normalize transport shape without making a semantic action judgment."""
    if isinstance(raw_plan, dict):
        return raw_plan
    candidate = str(raw_plan or "").strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1:]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3].rstrip()
    try:
        parsed = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    # Local models sometimes reach the output limit after already emitting the
    # complete action and candidate fields. Recover only those closed JSON
    # string fields. The ID must still be an opaque member of Python's catalog;
    # incomplete paths, commands, arguments and invented IDs remain unusable.
    action_match = re.search(
        r'"action"\s*:\s*"(OPEN_APP|LIST_LIBRARY|VOLUME_UP|VOLUME_DOWN|VOLUME_MUTE|MEDIA_PLAY_PAUSE|MEDIA_NEXT|MEDIA_PREVIOUS|BRIGHTNESS_UP|BRIGHTNESS_DOWN|FOCUS_WINDOW|MINIMIZE_WINDOW|MAXIMIZE_WINDOW|RESTORE_WINDOW|UNSUPPORTED|CLARIFY)"',
        candidate,
        re.IGNORECASE,
    )
    id_match = re.search(
        r'"candidate_id"\s*:\s*"([A-Za-z0-9_-]{1,64})"',
        candidate,
    )
    library_match = re.search(
        r'"library_type"\s*:\s*"(STEAM_GAMES|LOCAL_MUSIC)"',
        candidate,
        re.IGNORECASE,
    )
    recovered_action = action_match.group(1).upper() if action_match else ""
    if recovered_action == "OPEN_APP" and id_match:
        recovered_id = id_match.group(1)
        if recovered_id in valid_ids:
            return {
                "action": "OPEN_APP",
                "candidate_id": recovered_id,
                "reason": "Recovered complete bounded fields from truncated AI JSON.",
            }
    if recovered_action == "LIST_LIBRARY" and library_match:
        return {
            "action": "LIST_LIBRARY",
            "candidate_id": None,
            "library_type": library_match.group(1).upper(),
            "reason": "Recovered complete bounded fields from truncated AI JSON.",
        }
    if recovered_action in SYSTEM_CONTROL_ACTIONS:
        return {
            "action": recovered_action,
            "candidate_id": None,
            "reason": "Recovered complete bounded system action from truncated AI JSON.",
        }
    if recovered_action in WINDOW_CONTROL_ACTIONS and id_match:
        recovered_id = id_match.group(1)
        if recovered_id in valid_ids:
            return {
                "action": recovered_action,
                "candidate_id": recovered_id,
                "reason": "Recovered complete bounded window action from truncated AI JSON.",
            }

    # A bare opaque ID is an unambiguous AI selection. It cannot inject a path,
    # executable, argument or command because unknown IDs are rejected.
    bare_id = candidate.strip().strip('"').strip("'")
    if bare_id in valid_ids:
        return {
            "action": "OPEN_APP",
            "candidate_id": bare_id,
            "reason": "AI selected a discovered application by catalog ID.",
        }
    return None


def _nearby_executables(target, max_depth=5):
    """Collect bounded executable evidence near a resolved shortcut target."""
    if not target or not os.path.isfile(target):
        return []
    root = os.path.dirname(target)
    base_depth = len(Path(root).parts)
    items = []
    seen = set()
    for folder, folders, files in os.walk(root):
        depth = len(Path(folder).parts) - base_depth
        if depth >= max_depth:
            folders[:] = []
        for filename in files:
            if not filename.lower().endswith(".exe"):
                continue
            path = os.path.abspath(os.path.join(folder, filename))
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "id": _candidate_id("expected_executable", path),
                    "name": filename[:160],
                    "path": path,
                }
            )
            if len(items) >= MAX_EXPECTED_EXECUTABLES:
                return items
    return items


def _launch_strategy_evidence(candidate):
    """Build opaque, local-only choices; no semantic launcher judgment here."""
    if candidate.get("kind") != "shortcut":
        return None
    shortcut = _resolve_windows_shortcut(candidate.get("path", ""))
    target = _local_path(shortcut.get("target", ""))
    arguments = str(shortcut.get("arguments", "") or "").strip()
    working = _local_path(shortcut.get("working", ""))
    if not target:
        return None
    strategies = [
        {
            "id": _candidate_id("launch_strategy", candidate["path"]),
            "kind": "OPEN_ORIGINAL_SHORTCUT",
            "description": "Open the installed shortcut exactly as Windows registered it.",
            "path": candidate["path"],
            "arguments": [],
            "working": "",
        }
    ]
    if target and os.path.isfile(target) and target.lower().endswith(".exe"):
        strategies.append(
            {
                "id": _candidate_id(
                    "launch_strategy", target + "\0" + arguments
                ),
                "kind": "OPEN_RESOLVED_TARGET",
                "description": (
                    "Open the shortcut's resolved executable with its original "
                    "registered arguments."
                ),
                "path": target,
                "arguments": arguments,
                "working": working,
            }
        )
    windows = [
        {
            "id": _candidate_id("launcher_window", title),
            "title": title,
        }
        for title in _visible_window_titles()[:40]
    ]
    return {
        "strategies": strategies[:MAX_LAUNCH_STRATEGIES],
        "executables": _nearby_executables(target),
        "windows": windows,
    }


def _normalize_strategy_plan(raw_plan):
    if isinstance(raw_plan, dict):
        return raw_plan
    try:
        value = json.loads(str(raw_plan or "").strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def retry_launch_strategy(public_evidence):
    """Retry one truncated strategy decision with a compact local AI."""
    import tools

    compact = {
        "application": public_evidence["selected_application"]["name"],
        "strategies": public_evidence["strategies"],
        "executables": public_evidence["expected_executables"][:50],
        "windows": public_evidence["visible_windows"][:30],
    }
    return tools.run_ai_prompt(
        "prompts/casper_launch_strategy_retry.txt",
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")),
        expect_json=True,
        num_ctx=4096,
        num_predict=120,
        think=False,
        model_name="llama3.2:latest",
    )


def adapt_launch_candidate(candidate):
    """Let AI select one validated strategy derived from local shortcut data."""
    evidence = _launch_strategy_evidence(candidate)
    if not evidence:
        return candidate
    import tools

    public_evidence = {
        "selected_application": {
            "name": candidate.get("name", ""),
            "kind": candidate.get("kind", ""),
        },
        "strategies": [
            {
                "id": item["id"],
                "kind": item["kind"],
                "description": item["description"],
                "target_name": Path(item["path"]).name,
                "registered_arguments": str(item.get("arguments", ""))[:300],
            }
            for item in evidence["strategies"]
        ],
        "expected_executables": [
            {"id": item["id"], "name": item["name"]}
            for item in evidence["executables"]
        ],
        "visible_windows": evidence["windows"],
    }
    raw = tools.run_ai_prompt(
        "prompts/casper_launch_strategy.txt",
        json.dumps(public_evidence, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=4096,
        num_predict=220,
        think=False,
        model_name="llama3.2:latest",
    )
    plan = _normalize_strategy_plan(raw)
    if not plan:
        plan = _normalize_strategy_plan(retry_launch_strategy(public_evidence))
    if not plan:
        return candidate
    strategies = {item["id"]: item for item in evidence["strategies"]}
    executables = {item["id"]: item for item in evidence["executables"]}
    windows = {item["id"]: item for item in evidence["windows"]}
    strategy = strategies.get(str(plan.get("strategy_id") or ""))
    if not strategy:
        return candidate
    result = dict(candidate)
    if strategy["kind"] == "OPEN_RESOLVED_TARGET":
        result["kind"] = "launcher_game"
        result["path"] = strategy["path"]
        # Arguments originated in the installed shortcut, never in model text.
        result["launcher_arguments"] = _split_windows_arguments(
            strategy["arguments"]
        )
        if strategy.get("working") and os.path.isdir(strategy["working"]):
            result["working_directory"] = strategy["working"]
    expected = executables.get(
        str(plan.get("expected_executable_id") or "")
    )
    if expected:
        result["expected_game_executable"] = expected["name"]
    window = windows.get(str(plan.get("launcher_window_id") or ""))
    if window:
        result["launcher_name"] = window["title"]
    elif result.get("kind") == "launcher_game":
        result["launcher_name"] = Path(result["path"]).stem
    return result


def _split_windows_arguments(value):
    """Parse registered shortcut arguments without executing a shell."""
    value = str(value or "").strip()
    if not value:
        return []
    # CommandLineToArgvW is the Windows-native parser for shortcut arguments.
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        argc = ctypes.c_int()
        parser = ctypes.windll.shell32.CommandLineToArgvW
        parser.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
        parser.restype = ctypes.POINTER(wintypes.LPWSTR)
        argv = parser(value, ctypes.byref(argc))
        if argv:
            try:
                return [argv[index] for index in range(argc.value)]
            finally:
                ctypes.windll.kernel32.LocalFree(ctypes.cast(argv, ctypes.c_void_p))
    return [value]


def _launch(candidate):
    if sys.platform != "win32":
        raise OSError("Local application launch is only available on Windows.")
    if candidate["kind"] == "steam_game":
        app_id = str(candidate.get("app_id", ""))
        if not app_id.isdigit():
            raise OSError("Steam game has an invalid local App ID.")
        os.startfile("steam://rungameid/" + app_id)
        return None
    path = candidate["path"]
    if candidate["kind"] == "shortcut":
        os.startfile(path)  # Windows opens the signed Start Menu shortcut.
        return None
    process = subprocess.Popen(
        [path] + list(candidate.get("launcher_arguments", [])),
        cwd=(
            candidate.get("working_directory")
            or os.path.dirname(path)
            or None
        ),
        shell=False,
        close_fds=True,
    )
    return process.pid


def _launch_elevated(candidate):
    """Request Windows UAC for one already-discovered executable."""
    if sys.platform != "win32":
        raise OSError("Elevation is only available on Windows.")
    if candidate.get("kind") not in {"executable", "launcher_game"}:
        raise OSError("This candidate cannot be elevated safely.")
    path = str(candidate.get("path", ""))
    if not path.lower().endswith(".exe") or not os.path.isfile(path):
        raise OSError("The approved executable is no longer available.")
    import ctypes

    result = _shell_execute_runas(
        ctypes.windll.shell32,
        path,
        candidate.get("launcher_arguments", []),
        os.path.dirname(path) or None,
    )
    if result <= 32:
        raise OSError("Windows elevation was cancelled or failed (code %s)." % result)
    return None


def _shell_execute_runas(shell32, path, arguments, working_directory):
    """Call ShellExecuteW with its pointer and parameter positions intact."""
    parameters = subprocess.list2cmdline(list(arguments or [])) or None
    return shell32.ShellExecuteW(
        None,  # hwnd
        "runas",
        path,
        parameters,
        working_directory,
        1,
    )


def _visible_window_titles():
    if sys.platform != "win32":
        return []
    import ctypes

    user32 = ctypes.windll.user32
    titles = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(window_handle, _):
        if not user32.IsWindowVisible(window_handle):
            return True
        length = user32.GetWindowTextLengthW(window_handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window_handle, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            titles.append(title[:200])
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return titles[:160]


def discover_windows():
    """Return bounded visible top-level windows with opaque IDs."""
    if sys.platform != "win32":
        return []
    import ctypes

    user32 = ctypes.windll.user32
    items = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p
    )

    def collect(window_handle, _):
        if not user32.IsWindowVisible(window_handle):
            return True
        length = user32.GetWindowTextLengthW(window_handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window_handle, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            items.append(
                {
                    "id": _candidate_id(
                        "window", str(int(window_handle)) + "\0" + title
                    ),
                    "name": title[:200],
                    "kind": "window",
                    "window_handle": int(window_handle),
                }
            )
        return len(items) < 80

    user32.EnumWindows(callback_type(collect), 0)
    return items


def execute_system_control(action):
    """Execute one fixed low-risk Windows control; never accepts raw keys."""
    if sys.platform != "win32" or action not in SYSTEM_CONTROL_ACTIONS:
        return False
    if action.startswith("BRIGHTNESS_"):
        environment = os.environ.copy()
        environment["BEKKI_BRIGHTNESS_DELTA"] = (
            "10" if action == "BRIGHTNESS_UP" else "-10"
        )
        script = r'''
$delta=[int]$env:BEKKI_BRIGHTNESS_DELTA
$current=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
$method=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
if($null -eq $current -or $null -eq $method){'{"success":false}';exit}
$target=[Math]::Max(0,[Math]::Min(100,[int]$current.CurrentBrightness+$delta))
Invoke-CimMethod -InputObject $method -MethodName WmiSetBrightness -Arguments @{Timeout=1;Brightness=[byte]$target} | Out-Null
'{"success":true,"value":'+$target+'}'
'''
        result = _powershell_json(script, environment)
        return isinstance(result, dict) and result.get("success") is True

    import ctypes

    virtual_keys = {
        "VOLUME_MUTE": 0xAD,
        "VOLUME_DOWN": 0xAE,
        "VOLUME_UP": 0xAF,
        "MEDIA_NEXT": 0xB0,
        "MEDIA_PREVIOUS": 0xB1,
        "MEDIA_PLAY_PAUSE": 0xB3,
    }
    key = virtual_keys[action]
    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(key, 0, 2, 0)
    return True


def execute_window_control(action, candidate):
    """Apply one bounded non-destructive action to one still-valid window."""
    if (
        sys.platform != "win32"
        or action not in WINDOW_CONTROL_ACTIONS
        or candidate.get("kind") != "window"
    ):
        return False
    import ctypes

    user32 = ctypes.windll.user32
    window_handle = int(candidate.get("window_handle") or 0)
    if not window_handle or not user32.IsWindow(window_handle):
        return False
    length = user32.GetWindowTextLengthW(window_handle)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(window_handle, buffer, len(buffer))
    if buffer.value.strip() != candidate.get("name", ""):
        return False
    if action == "FOCUS_WINDOW":
        user32.ShowWindow(window_handle, 9)
        return bool(user32.SetForegroundWindow(window_handle))
    show_commands = {
        "MINIMIZE_WINDOW": 6,
        "MAXIMIZE_WINDOW": 3,
        "RESTORE_WINDOW": 9,
    }
    user32.ShowWindow(window_handle, show_commands[action])
    return True


def _running_processes():
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    items = []
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 2 or not row[1].isdigit():
            continue
        items.append({"name": row[0][:160], "pid": int(row[1])})
    return items[:1000]


def _runtime_snapshot():
    return {
        "processes": _running_processes(),
        "windows": _visible_window_titles(),
    }


def _powershell_json(script, environment, timeout=10):
    """Run one fixed local PowerShell inspection/action and decode JSON."""
    if sys.platform != "win32":
        return None
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        return json.loads(completed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def discover_launcher_controls(candidate):
    """Return bounded, invokable controls from the already discovered launcher."""
    launcher_name = str(candidate.get("launcher_name") or "").strip()
    if not launcher_name:
        return []
    environment = os.environ.copy()
    environment["BEKKI_LAUNCHER_NAME"] = launcher_name
    script = r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$window=$null
foreach($item in $windows){if($item.Current.Name -like "*$env:BEKKI_LAUNCHER_NAME*"){$window=$item;break}}
if($null -eq $window){'[]';exit}
$all=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$result=@()
for($i=0;$i -lt $all.Count -and $result.Count -lt 80;$i++){
  $item=$all.Item($i)
  $invoke=$null;$legacy=$null
  $hasInvoke=$item.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)
  $hasLegacy=$item.TryGetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$legacy)
  if(-not $item.Current.IsEnabled -or (-not $hasInvoke -and -not $hasLegacy)){continue}
  $result += [pscustomobject]@{
    ordinal=$i;name=[string]$item.Current.Name;automation_id=[string]$item.Current.AutomationId;
    class_name=[string]$item.Current.ClassName;control_type=[string]$item.Current.ControlType.ProgrammaticName
  }
}
ConvertTo-Json -Compress -InputObject @($result)
'''
    raw = _powershell_json(script, environment)
    if not isinstance(raw, list):
        return []
    controls = []
    for item in raw[:MAX_LAUNCHER_CONTROLS]:
        if not isinstance(item, dict):
            continue
        bounded = {
            "ordinal": int(item.get("ordinal", -1)),
            "name": str(item.get("name", ""))[:160],
            "automation_id": str(item.get("automation_id", ""))[:160],
            "class_name": str(item.get("class_name", ""))[:120],
            "control_type": str(item.get("control_type", ""))[:120],
        }
        bounded["id"] = _candidate_id(
            "launcher_control",
            launcher_name + "\0" + json.dumps(bounded, sort_keys=True),
        )
        controls.append(bounded)
    return controls


def choose_launcher_control(candidate, controls):
    """Let AI select one opaque launcher control; never accept commands/coords."""
    if not controls:
        return None
    import tools

    payload = {
        "requested_game": candidate.get("name", ""),
        "launcher": candidate.get("launcher_name", ""),
        "controls": [
            {key: item[key] for key in ("id", "name", "automation_id", "control_type")}
            for item in controls
        ],
    }
    plan = tools.run_ai_prompt(
        "prompts/casper_launcher_control.txt",
        json.dumps(payload, ensure_ascii=False, indent=2),
        expect_json=True,
        num_ctx=4096,
        num_predict=180,
        think=False,
        model_name="llama3.2:latest",
    )
    if not isinstance(plan, dict) or str(plan.get("action", "")).upper() != "INVOKE":
        return None
    selected_id = str(plan.get("control_id") or "")
    return next((item for item in controls if item["id"] == selected_id), None)


def choose_observed_launcher_window(candidate, verification):
    """Ask AI which observed window belongs to this launcher-mediated game."""
    titles = list(
        dict.fromkeys(
            str(title)[:200]
            for title in verification.get("evidence", {}).get(
                "visible_windows_after", []
            )
            if str(title).strip()
        )
    )[:50]
    if not titles:
        return ""
    choices = [
        {"id": _candidate_id("observed_launcher_window", title), "title": title}
        for title in titles
    ]
    import tools

    raw = tools.run_ai_prompt(
        "prompts/casper_launcher_window.txt",
        json.dumps(
            {
                "requested_application": candidate.get("name", ""),
                "launch_target": Path(candidate.get("path", "")).name,
                "expected_executable": candidate.get(
                    "expected_game_executable", ""
                ),
                "windows": choices,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        expect_json=False,
        num_ctx=2048,
        num_predict=60,
        think=False,
        model_name="llama3.2:latest",
    )
    selected_id = str(raw or "").strip().strip('"').strip("'")
    by_id = {item["id"]: item["title"] for item in choices}
    return by_id.get(selected_id, "")


def invoke_launcher_control(candidate, control):
    """Reacquire and invoke exactly one AI-selected bounded UIA control."""
    if not control:
        return False
    environment = os.environ.copy()
    environment.update(
        {
            "BEKKI_LAUNCHER_NAME": str(candidate.get("launcher_name") or ""),
            "BEKKI_CONTROL_ORDINAL": str(control.get("ordinal", -1)),
        }
    )
    script = r'''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root=[System.Windows.Automation.AutomationElement]::RootElement
$windows=$root.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
$window=$null
foreach($item in $windows){if($item.Current.Name -like "*$env:BEKKI_LAUNCHER_NAME*"){$window=$item;break}}
if($null -eq $window){'{"success":false}';exit}
$all=$window.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
$index=[int]$env:BEKKI_CONTROL_ORDINAL
if($index -lt 0 -or $index -ge $all.Count){'{"success":false}';exit}
$item=$all.Item($index);$pattern=$null
if($item.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){$pattern.Invoke();'{"success":true}';exit}
if($item.TryGetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern,[ref]$pattern)){$pattern.DoDefaultAction();'{"success":true}';exit}
'{"success":false}'
'''
    result = _powershell_json(script, environment)
    return isinstance(result, dict) and result.get("success") is True


def capture_launcher_window(candidate):
    """Capture only the bounded visible launcher window for local Vision."""
    if sys.platform != "win32":
        return None
    launcher_name = str(candidate.get("launcher_name") or "").casefold().strip()
    if not launcher_name:
        return None
    import ctypes
    from ctypes import wintypes
    from PIL import ImageGrab

    user32 = ctypes.windll.user32
    matches = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect(window_handle, _):
        if not user32.IsWindowVisible(window_handle):
            return True
        length = user32.GetWindowTextLengthW(window_handle)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window_handle, buffer, length + 1)
        if launcher_name in buffer.value.casefold():
            matches.append(int(window_handle))
            return False
        return True

    user32.EnumWindows(callback_type(collect), 0)
    if not matches:
        return None
    window_handle = matches[0]
    hwnd = ctypes.c_void_p(window_handle)
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        return None
    bounds = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
    if bounds[2] - bounds[0] < 120 or bounds[3] - bounds[1] < 100:
        return None
    try:
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)
        image = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
        folder = os.path.join(tempfile.gettempdir(), "Bekki")
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, "casper_launcher_window.jpg")
        image.save(file_path, format="JPEG", quality=88, optimize=True)
    except Exception:
        return None
    return {
        "window_handle": window_handle,
        "bounds": bounds,
        "file_path": file_path,
        "size": image.size,
    }


def click_visual_launcher_target(capture, target):
    """Click one validated normalized point inside the captured launcher only."""
    if sys.platform != "win32" or not capture or not isinstance(target, dict):
        return False
    if target.get("action") != "CLICK":
        return False
    try:
        x_value, y_value = float(target["x"]), float(target["y"])
        left, top, right, bottom = capture["bounds"]
        window_handle = int(capture["window_handle"])
    except (KeyError, TypeError, ValueError):
        return False
    if not 0 <= x_value <= 1000 or not 0 <= y_value <= 1000:
        return False
    # Keep the click away from the title bar/window frame while remaining
    # entirely inside the launcher window authorized by the user.
    x = round(left + (right - left) * x_value / 1000)
    y = round(top + (bottom - top) * y_value / 1000)
    if not left + 4 <= x <= right - 4 or not top + 28 <= y <= bottom - 4:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = ctypes.c_void_p(window_handle)
    if not user32.IsWindow(hwnd):
        print("[CASPER VISUAL CLICK] rejected invalid launcher HWND")
        return False
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    if not user32.SetCursorPos(x, y):
        print("[CASPER VISUAL CLICK] SetCursorPos failed; trying SendInput", x, y)
        if not _send_absolute_click(user32, x, y):
            print("[CASPER VISUAL CLICK] SendInput failed", x, y)
            return False
        print("[CASPER VISUAL CLICK] clicked with SendInput", x, y)
        return True
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    print("[CASPER VISUAL CLICK] clicked with SetCursorPos", x, y)
    return True


def _send_absolute_click(user32, x, y):
    """Use SendInput as a pointer-size-safe fallback for a bounded click."""
    import ctypes
    from ctypes import wintypes

    virtual_left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    virtual_top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    virtual_width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    virtual_height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if virtual_width <= 1 or virtual_height <= 1:
        return False
    dx = round((x - virtual_left) * 65535 / (virtual_width - 1))
    dy = round((y - virtual_top) * 65535 / (virtual_height - 1))
    if not 0 <= dx <= 65535 or not 0 <= dy <= 65535:
        return False

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("mi", MouseInput)]

    class Input(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

    move_flags = 0x0001 | 0x4000 | 0x8000  # MOVE | VIRTUALDESK | ABSOLUTE
    inputs = (Input * 3)(
        Input(type=0, mi=MouseInput(dx, dy, 0, move_flags, 0, 0)),
        Input(type=0, mi=MouseInput(0, 0, 0, 0x0002, 0, 0)),
        Input(type=0, mi=MouseInput(0, 0, 0, 0x0004, 0, 0)),
    )
    sent = user32.SendInput(3, inputs, ctypes.sizeof(Input))
    return int(sent) == 3


def _launch_evidence(candidate, before, after, launched_pid):
    before_pids = {item["pid"] for item in before.get("processes", [])}
    before_titles = set(before.get("windows", []))
    expected_executable = (
        str(candidate.get("expected_game_executable") or "")
        or os.path.basename(str(candidate.get("path", "")))
        if candidate.get("kind") != "shortcut"
        else ""
    )
    return {
        "requested_name": candidate.get("name", ""),
        "candidate_kind": candidate.get("kind", ""),
        "expected_executable": expected_executable,
        "known_launcher": candidate.get("launcher_name"),
        "launcher_target": os.path.basename(str(candidate.get("launcher_target", ""))),
        "launched_pid": launched_pid,
        "new_processes": [
            item for item in after.get("processes", []) if item["pid"] not in before_pids
        ][:40],
        "new_windows": [
            title for title in after.get("windows", []) if title not in before_titles
        ][:40],
        "visible_windows_after": after.get("windows", [])[:80],
        "matching_processes_after": [
            item
            for item in after.get("processes", [])
            if expected_executable
            and item.get("name", "").casefold() == expected_executable.casefold()
        ][:10],
    }


def _normalize_launch_judgment(raw_value):
    """Recover only complete AI-authored launch-verdict fields."""
    valid = {"GAME_OPENED", "APP_OPENED", "LAUNCHER_OPENED", "FAILED", "UNCERTAIN"}
    if isinstance(raw_value, dict):
        value = raw_value
    else:
        text_value = str(raw_value or "").strip()
        try:
            value = json.loads(text_value)
        except (json.JSONDecodeError, TypeError):
            value = None
        if not isinstance(value, dict):
            status_match = re.search(
                r'"status"\s*:\s*"(GAME_OPENED|APP_OPENED|LAUNCHER_OPENED|FAILED|UNCERTAIN)"',
                text_value,
                re.IGNORECASE,
            )
            if status_match:
                return {
                    "status": status_match.group(1).upper(),
                    "reason": "Recovered complete AI status from truncated JSON.",
                }
            return None
    status = str(value.get("status", "")).upper().strip()
    if status not in valid:
        return None
    return {"status": status, "reason": str(value.get("reason", ""))[:400]}


def _game_opened_has_evidence(evidence):
    """Require bounded target process/window evidence for GAME_OPENED."""
    if evidence.get("matching_processes_after"):
        return True
    requested = str(evidence.get("requested_name") or "").casefold().strip()
    if not requested:
        return False
    titles = list(evidence.get("new_windows", [])) + list(
        evidence.get("visible_windows_after", [])
    )
    return any(requested in str(title).casefold() for title in titles)


def _retry_launch_without_game_success(tools_module, evidence):
    """Ask AI to reclassify after GAME_OPENED fails its evidence invariant."""
    retry = tools_module.run_ai_prompt(
        "prompts/casper_launch_verify_no_game.txt",
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        expect_json=False,
        num_ctx=2048,
        num_predict=80,
        think=False,
        model_name="llama3.2:latest",
    )
    status = str(retry or "").strip().upper()
    if status in {"LAUNCHER_OPENED", "FAILED", "UNCERTAIN"}:
        return status
    return "UNCERTAIN"


def verify_launch(candidate, before, launched_pid, wait_seconds=6):
    """Let AI judge observed post-launch state from bounded Windows evidence."""
    import tools

    attempts = max(1, int((max(float(wait_seconds), 0.1) + 2.9) // 3))
    evidence = None
    for attempt in range(attempts):
        time.sleep(min(3, max(float(wait_seconds), 0.1)))
        evidence = _launch_evidence(
            candidate,
            before,
            _runtime_snapshot(),
            launched_pid,
        )
        # Exact target process/window evidence is a safe reason to stop
        # polling early. AI still owns the final launch-state judgment.
        if _game_opened_has_evidence(evidence):
            break
    raw_judgment = tools.run_ai_prompt(
        "prompts/casper_launch_verify.txt",
        json.dumps(evidence, ensure_ascii=False, indent=2),
        expect_json=False,
        num_ctx=4096,
        num_predict=260,
        think=False,
        model_name="llama3.2:latest",
    )
    valid = {"GAME_OPENED", "APP_OPENED", "LAUNCHER_OPENED", "FAILED", "UNCERTAIN"}
    judgment = _normalize_launch_judgment(raw_judgment)
    if not isinstance(judgment, dict):
        retry = tools.run_ai_prompt(
            "prompts/casper_launch_verify_retry.txt",
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
            expect_json=False,
            num_ctx=2048,
            num_predict=80,
            think=False,
            model_name="llama3.2:latest",
        )
        retry_status = str(retry or "").strip().upper()
        if retry_status in valid:
            if retry_status == "GAME_OPENED" and not _game_opened_has_evidence(evidence):
                retry_status = _retry_launch_without_game_success(tools, evidence)
                retry_reason = (
                    "AI reclassified launch after unsupported GAME_OPENED "
                    "verdict was rejected."
                )
            else:
                retry_reason = "AI launch verifier compact retry."
            return {
                "status": retry_status,
                "reason": retry_reason,
                "evidence": evidence,
            }
        return {
            "status": "UNCERTAIN",
            "reason": "Launch verifier returned invalid output twice.",
            "evidence": evidence,
        }
    status = str(judgment.get("status", "")).upper().strip()
    if status not in valid:
        status = "UNCERTAIN"
    if status == "GAME_OPENED" and not _game_opened_has_evidence(evidence):
        status = _retry_launch_without_game_success(tools, evidence)
        judgment["reason"] = (
            "AI reclassified launch after unsupported GAME_OPENED verdict "
            "was rejected."
        )
    return {
        "status": status,
        "reason": str(judgment.get("reason", ""))[:400],
        "evidence": evidence,
    }


def execute_user_request(
    message,
    recent_context,
    applications=None,
    launcher=None,
    elevation_approved=False,
    device_approval=None,
):
    # A confirmed bounded action resumes through its owning executor. The
    # opaque approval payload is authority; generic AI cannot reinterpret it
    # as an unrelated app/window operation on the confirmation turn.
    if (
        isinstance(device_approval, dict)
        and device_approval.get("action") == "restore_recycle_item"
    ):
        from . import recycle_bin

        return recycle_bin.execute(
            message, recent_context, approval=device_approval
        )

    # Recycle Bin requests have their own compact semantic gate before the
    # generic device planner. This keeps them reachable even when the generic
    # planner truncates or emits an unrelated valid action.
    recycle_scope = classify_recycle_bin_scope(message, recent_context)
    if recycle_scope == "RECYCLE_BIN_ACTION":
        from . import recycle_bin

        return recycle_bin.execute(message, recent_context, approval=None)

    raw_transport, applications = plan_user_request(
        message,
        recent_context,
        applications=applications,
    )
    by_id = {item["id"]: item for item in applications}
    raw_plan = _normalize_plan(raw_transport, set(by_id))
    if (
        not isinstance(raw_plan, dict)
        and _plan_transport_needs_retry(raw_transport)
    ):
        retry_transport = retry_open_app_selection(
            message,
            recent_context,
            applications,
        )
        raw_plan = _normalize_plan(retry_transport, set(by_id))
    if isinstance(raw_plan, dict):
        planned_action = str(raw_plan.get("action", "")).upper().strip()
        if planned_action not in DEVICE_PLAN_ACTIONS:
            retry_transport = retry_open_app_selection(
                message,
                recent_context,
                applications,
            )
            raw_plan = _normalize_plan(retry_transport, set(by_id))
    if not isinstance(raw_plan, dict):
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "我没有可靠地识别出要打开哪个应用，可以说出完整名称吗？",
            "reason": "Device planner returned invalid structured output.",
        }

    action = str(raw_plan.get("action", "")).upper().strip()
    candidate_id = str(raw_plan.get("candidate_id") or "").strip()
    if action not in DEVICE_PLAN_ACTIONS:
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "我没有可靠地解析这个设备操作，可以再说一次吗？",
            "reason": "Compact device planner returned an invalid action.",
        }

    action_family = ""
    # A generic LIST_LIBRARY plan is not trusted to distinguish a media/game
    # library from an ordinary user folder. A dedicated two-choice AI makes
    # that semantic decision; Python only validates the bounded token.
    if action == "LIST_LIBRARY":
        scope = classify_file_or_library_scope(message, recent_context)
        if scope == "FILE_ACTION":
            from . import file_actions

            return file_actions.execute(message, recent_context)
        if scope == "RECYCLE_BIN_ACTION":
            from . import recycle_bin

            return recycle_bin.execute(
                message, recent_context, approval=device_approval
            )
        if scope == "":
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "你想查看普通文件夹、游戏或音乐库，还是 Windows 回收站？",
                "reason": "Focused local-data scope AI returned invalid output twice.",
            }

    if action in {"UNSUPPORTED", "CLARIFY"} or (
        action == "OPEN_APP"
        and any(item.get("kind") == "window" for item in applications)
    ):
        action_family = classify_device_action_family(
            message, recent_context
        )
    if action_family == "FILE_ACTION":
        from . import file_actions

        return file_actions.execute(message, recent_context)
    if action_family == "RECYCLE_BIN_ACTION":
        from . import recycle_bin

        return recycle_bin.execute(
            message, recent_context, approval=device_approval
        )

    # A window ID can never be launched as an application. This is a schema
    # type mismatch, not a semantic judgment; focused AI still decides the
    # actual window action and target from the bounded visible-window catalog.
    focused_window_plan = None
    if action == "OPEN_APP" and any(
        item.get("kind") == "window" for item in applications
    ):
        if action_family == "WINDOW_CONTROL":
            focused_window_plan = select_window_action(
                message, recent_context, applications
            )
            if not focused_window_plan:
                return {
                    "success": False,
                    "needs_clarification": True,
                    "clarification": "没有找到与你描述相符的已打开窗口。需要我打开对应应用吗？",
                    "reason": "AI classified the request as window control but found no exact visible match.",
                }
            action = focused_window_plan["action"]
            candidate_id = focused_window_plan["candidate_id"]

    selected_resource = by_id.get(candidate_id)
    if (
        action == "OPEN_APP"
        and isinstance(selected_resource, dict)
        and selected_resource.get("kind") == "window"
    ):
        focused_window_plan = select_window_action(
            message, recent_context, applications
        )
        if not focused_window_plan:
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "没有找到与你描述相符的已打开窗口。需要我打开对应应用吗？",
                "reason": "AI paired OPEN_APP with a window ID and focused window selection found no exact match.",
            }
        action = focused_window_plan["action"]
        candidate_id = focused_window_plan["candidate_id"]

    if action in SYSTEM_CONTROL_ACTIONS:
        completed = execute_system_control(action)
        return {
            "success": completed,
            "completed": completed,
            "needs_clarification": False,
            "action": "system_control_completed" if completed else "failed",
            "control": action,
            "reason": (
                "The fixed Windows control was executed."
                if completed
                else "The requested Windows control is unavailable on this device."
            ),
        }

    if action in WINDOW_CONTROL_ACTIONS:
        if focused_window_plan is None:
            focused_window_plan = select_window_action(
                message, recent_context, applications
            )
        if focused_window_plan:
            action = focused_window_plan["action"]
            candidate_id = focused_window_plan["candidate_id"]
        else:
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "没有找到与你描述相符的已打开窗口。需要我打开对应应用吗？",
                "reason": "Focused AI window selection found no exact visible match.",
            }
        window = by_id.get(candidate_id)
        if not window or window.get("kind") != "window":
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "你想操作哪个当前打开的窗口？",
                "reason": "AI did not select one discovered window ID.",
            }
        completed = execute_window_control(action, window)
        return {
            "success": completed,
            "completed": completed,
            "needs_clarification": False,
            "action": "window_control_completed" if completed else "failed",
            "control": action,
            "window": window.get("name", ""),
            "reason": (
                "The selected bounded window action was executed."
                if completed
                else "The selected window changed or is no longer available."
            ),
        }

    if action == "LIST_LIBRARY":
        library_type = str(raw_plan.get("library_type") or "").upper().strip()
        if library_type == "STEAM_GAMES":
            items = list_installed_steam_games(applications)
            return {
                "success": True,
                "needs_clarification": False,
                "action": "listed_library",
                "library_type": library_type,
                "count": len(items),
                "items": items,
                "scope": "installed Steam games only",
            }
        if library_type == "LOCAL_MUSIC":
            items = list_local_music()
            return {
                "success": True,
                "needs_clarification": False,
                "action": "listed_library",
                "library_type": library_type,
                "count": len(items),
                "items": items,
                "scope": "audio files in Windows Music folders only",
            }
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "你想查看已安装的 Steam 游戏，还是电脑音乐文件夹里的歌曲？",
            "reason": "AI did not select a supported local library type.",
        }

    if action == "CLARIFY":
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": str(raw_plan.get("clarification") or "你想打开哪个应用？")[:300],
            "reason": str(raw_plan.get("reason", ""))[:300],
        }
    if action != "OPEN_APP":
        return {
            "success": False,
            "needs_clarification": False,
            "unsupported": True,
            "reason": str(raw_plan.get("reason") or "This device action is not supported yet.")[:300],
        }
    candidate = by_id.get(candidate_id)
    if candidate is None:
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "我没有在已安装应用里可靠地找到它，可以确认应用的完整名称吗？",
            "reason": "AI selected an application ID outside the discovered catalog.",
        }

    candidate = adapt_launch_candidate(candidate)

    before = _runtime_snapshot() if launcher is None else {}
    try:
        launched_pid = (launcher or _launch)(candidate)
    except OSError as error:
        if getattr(error, "winerror", None) == 740:
            if not elevation_approved:
                return {
                    "success": False,
                    "needs_clarification": False,
                    "requires_approval": True,
                    "approval_type": "permission_escalation",
                    "application": candidate["name"],
                    "reason": "Windows requires administrator approval to launch this application.",
                }
            try:
                launched_pid = _launch_elevated(candidate)
            except OSError as elevated_error:
                return {
                    "success": False,
                    "needs_clarification": False,
                    "application": candidate["name"],
                    "reason": "Elevated application launch failed: " + str(elevated_error)[:300],
                }
        else:
            return {
                "success": False,
                "needs_clarification": False,
                "application": candidate["name"],
                "reason": "Application launch failed: " + str(error)[:300],
            }
    verification = (
        verify_launch(candidate, before, launched_pid)
        if launcher is None
        else None
    )
    launcher_interaction = None
    if (
        launcher is None
        and isinstance(verification, dict)
        and verification.get("status") == "LAUNCHER_OPENED"
        and candidate.get("kind") == "launcher_game"
    ):
        observed_launcher = choose_observed_launcher_window(
            candidate, verification
        )
        if observed_launcher:
            candidate["launcher_name"] = observed_launcher
        controls = discover_launcher_controls(candidate)
        selected_control = choose_launcher_control(candidate, controls)
        interaction_before = _runtime_snapshot()
        invoked = invoke_launcher_control(candidate, selected_control)
        launcher_interaction = {
            "method": "accessibility" if controls else "none",
            "control_count": len(controls),
            "selected_control": (
                selected_control.get("name", "") if selected_control else ""
            ),
            "invoked": invoked,
        }
        if invoked:
            verification = verify_launch(
                candidate,
                interaction_before,
                None,
                wait_seconds=35,
            )
        elif not controls:
            capture = capture_launcher_window(candidate)
            visual_target = None
            clicked = False
            if capture:
                import vision

                visual_target = vision.locate_launcher_start_control(
                    capture["file_path"],
                    candidate.get("launcher_name", ""),
                    candidate.get("name", ""),
                )
                interaction_before = _runtime_snapshot()
                clicked = click_visual_launcher_target(capture, visual_target)
            launcher_interaction.update(
                {
                    "method": "vision" if capture else "none",
                    "visual_label": (
                        str(visual_target.get("label", ""))[:120]
                        if isinstance(visual_target, dict)
                        else ""
                    ),
                    "visual_confidence": (
                        visual_target.get("confidence")
                        if isinstance(visual_target, dict)
                        else None
                    ),
                    "visual_point": (
                        [visual_target.get("x"), visual_target.get("y")]
                        if isinstance(visual_target, dict)
                        and visual_target.get("action") == "CLICK"
                        else None
                    ),
                    "clicked": clicked,
                }
            )
            if clicked:
                verification = verify_launch(
                    candidate,
                    interaction_before,
                    None,
                    wait_seconds=35,
                )
    verified_status = (
        verification.get("status")
        if isinstance(verification, dict)
        else None
    )
    completed = (
        verified_status in {"GAME_OPENED", "APP_OPENED"}
        if verified_status
        else not bool(candidate.get("launcher_only"))
    )
    return {
        "success": completed,
        "completed": completed,
        "needs_clarification": False,
        "application": candidate["name"],
        "action": (
            verified_status.lower()
            if verified_status
            else (
                "launcher_opened"
                if candidate.get("launcher_only")
                else "opened"
            )
        ),
        "launcher": candidate.get("launcher_name"),
        "verification": verification,
        "launcher_interaction": launcher_interaction,
    }
