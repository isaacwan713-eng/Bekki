"""AI-selected, bounded installation of downloaded game content."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


MAX_SOURCE_FILES = 120
MAX_TACTIC_BYTES = 64 * 1024 * 1024
MAX_SPORTS_INTERACTIVE_GAMES = 40


def _opaque_id(kind, value):
    payload = (str(kind) + "\0" + os.path.normcase(str(value))).encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha256(payload).hexdigest()[:16]


def _windows_personal_documents():
    """Read Windows' configured Documents known-folder location."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = (
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, "Personal")
        expanded = os.path.expandvars(str(value or "").strip())
        return Path(expanded) if expanded else None
    except (ImportError, OSError):
        return None


def _candidate_user_folders():
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    folders = [home / "Documents", home / "Downloads"]
    configured_documents = _windows_personal_documents()
    if configured_documents is not None:
        folders.append(configured_documents)
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(variable)
        if value:
            root = Path(value)
            folders.extend((root / "Documents", root / "Downloads"))
    result = []
    seen = set()
    for folder in folders:
        absolute = os.path.abspath(os.path.expandvars(str(folder)))
        key = os.path.normcase(absolute)
        if key not in seen:
            seen.add(key)
            result.append(Path(absolute))
    return result


def discover_fm_tactic_sources():
    """Find bounded .fmf candidates under actual Downloads folders."""
    sources = []
    seen = set()
    downloads = [
        folder for folder in _candidate_user_folders()
        if folder.name.casefold() == "downloads" and folder.is_dir()
    ]
    for root in downloads:
        try:
            iterator = root.rglob("*.fmf")
            for path in iterator:
                try:
                    relative = path.relative_to(root)
                    if len(relative.parts) > 3 or path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                except OSError:
                    continue
                if size <= 0 or size > MAX_TACTIC_BYTES:
                    continue
                absolute = os.path.abspath(str(path))
                key = os.path.normcase(absolute)
                if key in seen:
                    continue
                seen.add(key)
                sources.append(
                    {
                        "id": _opaque_id("fm_tactic_source", absolute),
                        "name": path.name[:240],
                        "path": absolute,
                        "size": size,
                        "kind": "fm_tactic_source",
                    }
                )
                if len(sources) >= MAX_SOURCE_FILES:
                    return sources
        except OSError:
            continue
    return sources


def discover_fm_tactic_destinations():
    """Enumerate bounded existing game roots; AI chooses the semantic match."""
    destinations = []
    seen = set()
    documents = [
        folder for folder in _candidate_user_folders()
        if folder.name.casefold() != "downloads" and folder.is_dir()
    ]
    for documents_root in documents:
        publisher_root = documents_root / "Sports Interactive"
        if not publisher_root.is_dir() or publisher_root.is_symlink():
            continue
        try:
            game_roots = sorted(
                (
                    item
                    for item in publisher_root.iterdir()
                    if item.is_dir() and not item.is_symlink()
                ),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            continue
        for game_root in game_roots[:MAX_SPORTS_INTERACTIVE_GAMES]:
            tactics = game_root / "tactics"
            absolute = os.path.abspath(str(tactics))
            key = os.path.normcase(absolute)
            if key in seen:
                continue
            seen.add(key)
            destinations.append(
                {
                    "id": _opaque_id("fm_tactic_destination", absolute),
                    "name": game_root.name[:180] + " tactics",
                    "path": absolute,
                    "game_root": os.path.abspath(str(game_root)),
                    "kind": "fm_tactic_destination",
                }
            )
            if len(destinations) >= MAX_SPORTS_INTERACTIVE_GAMES:
                return destinations
    return destinations


def _select_install(message, recent_context, sources, destinations):
    """AI selects only opaque IDs from the discovered bounded catalogs."""
    import tools

    payload = {
        "sources": [
            {"id": item["id"], "name": item["name"], "size": item["size"]}
            for item in sources
        ],
        "destinations": [
            {"id": item["id"], "name": item["name"]}
            for item in destinations
        ],
        "recent_context": str(recent_context)[-600:],
        "request": str(message)[:600],
    }
    valid_sources = {item["id"] for item in sources}
    valid_destinations = {item["id"] for item in destinations}
    prompt_input = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for _attempt in range(2):
        decision = tools.run_ai_prompt(
            "prompts/casper_game_content_install.txt",
            prompt_input,
            expect_json=True,
            num_ctx=2048,
            num_predict=80,
            think=False,
            model_name="llama3.2:latest",
        )
        if isinstance(decision, dict):
            source_id = str(decision.get("source_id") or "")
            destination_id = str(decision.get("destination_id") or "")
            if source_id in valid_sources and destination_id in valid_destinations:
                return source_id, destination_id
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + str(decision)[:160]
    return "", ""


def _safe_destination_path(destination, source_name):
    root = os.path.abspath(destination["path"])
    game_root = os.path.abspath(destination["game_root"])
    if os.path.normcase(os.path.commonpath([game_root, root])) != os.path.normcase(game_root):
        raise OSError("The tactics directory escaped the discovered FM26 data root.")
    stem = Path(source_name).stem[:180] or "Bekki tactic"
    candidate = os.path.join(root, stem + ".fmf")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(root, stem + " (" + str(counter) + ").fmf")
        counter += 1
    return candidate


def _validate_source(source):
    path = Path(source["path"])
    if path.suffix.casefold() != ".fmf" or path.is_symlink() or not path.is_file():
        raise OSError("The selected source is not a regular .fmf file.")
    size = path.stat().st_size
    if size <= 0 or size > MAX_TACTIC_BYTES:
        raise OSError("The selected .fmf file has an unsafe size.")
    with path.open("rb") as handle:
        if handle.read(2) == b"MZ":
            raise OSError("The selected file contains a Windows executable header.")


def execute(message, recent_context):
    sources = discover_fm_tactic_sources()
    destinations = discover_fm_tactic_destinations()
    if not sources:
        return _clarify("没有在 Downloads 中找到可安装的 .fmf 战术文件。")
    if not destinations:
        return _clarify(
            "没有发现 Sports Interactive 下的现有游戏用户数据目录；"
            "请先运行一次目标游戏，让它创建用户数据文件夹。"
        )
    source_id, destination_id = _select_install(
        message, recent_context, sources, destinations
    )
    sources_by_id = {item["id"]: item for item in sources}
    destinations_by_id = {item["id"]: item for item in destinations}
    source = sources_by_id.get(source_id)
    destination = destinations_by_id.get(destination_id)
    if not source or not destination:
        return _clarify("没有可靠地选中要安装的战术文件和 FM26 目录。")
    try:
        _validate_source(source)
        os.makedirs(destination["path"], exist_ok=True)
        target = _safe_destination_path(destination, source["name"])
        shutil.copy2(source["path"], target)
        if not os.path.isfile(target) or os.path.getsize(target) != os.path.getsize(source["path"]):
            raise OSError("Installed file verification failed.")
    except OSError as error:
        return _failed("Installing the selected FM26 tactic failed: " + str(error)[:300])
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "installed_fm_tactic",
        "name": os.path.basename(target),
        "destination": destination["name"],
    }


def install_verified_fm_tactic(source_path, verified_destination_path):
    """Install one downloaded tactic only into a currently discovered root."""
    source_path = os.path.abspath(str(source_path))
    wanted = os.path.normcase(os.path.abspath(str(verified_destination_path)))
    destinations = discover_fm_tactic_destinations()
    destination = next(
        (
            item
            for item in destinations
            if os.path.normcase(os.path.abspath(item["path"])) == wanted
        ),
        None,
    )
    if not destination:
        return _clarify(
            "之前验证的 FM26 战术目录已经变化，需要重新学习安装方法。"
        )
    source = {
        "path": source_path,
        "name": os.path.basename(source_path),
    }
    try:
        _validate_source(source)
        os.makedirs(destination["path"], exist_ok=True)
        target = _safe_destination_path(destination, source["name"])
        shutil.copy2(source_path, target)
        if (
            not os.path.isfile(target)
            or os.path.getsize(target) != os.path.getsize(source_path)
        ):
            raise OSError("Installed file verification failed.")
    except OSError as error:
        return _failed("Installing the downloaded FM26 tactic failed: " + str(error)[:300])
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "installed_fm_tactic",
        "name": os.path.basename(target),
        "destination": destination["name"],
    }


def open_verified_fm_tactic_destination(verified_destination_path):
    """Reopen only an exact destination still present in the bounded catalog."""
    wanted = os.path.normcase(
        os.path.abspath(str(verified_destination_path or ""))
    )
    destination = next(
        (
            item
            for item in discover_fm_tactic_destinations()
            if os.path.normcase(os.path.abspath(item["path"])) == wanted
        ),
        None,
    )
    if not destination:
        return _clarify(
            "之前验证的 FM26 战术目录已经变化，需要重新学习文件夹技能。"
        )
    if sys.platform != "win32":
        return _clarify("本地目录打开功能目前仅支持 Windows。")
    try:
        os.makedirs(destination["path"], exist_ok=True)
        os.startfile(destination["path"])
    except OSError as error:
        return _failed("Opening the verified FM tactic folder failed: " + str(error)[:300])
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "opened_fm_tactic_folder",
        "name": destination["name"],
        "destination": destination["name"],
    }


def _clarify(message):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "clarification": message,
        "reason": message,
    }


def _failed(reason):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": False,
        "action": "failed",
        "reason": reason,
    }
