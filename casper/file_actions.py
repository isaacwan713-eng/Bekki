"""Bounded user-folder actions selected by AI and enforced by Python."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys


MAX_ENTRIES = 240


def _opaque_id(kind, value):
    payload = (str(kind) + "\0" + os.path.normcase(str(value))).encode(
        "utf-8", errors="ignore"
    )
    return hashlib.sha256(payload).hexdigest()[:16]


def discover_user_roots():
    home = os.environ.get("USERPROFILE") or str(Path.home())
    definitions = [
        ("Desktop", os.path.join(home, "Desktop")),
        ("Documents", os.path.join(home, "Documents")),
        ("Downloads", os.path.join(home, "Downloads")),
        ("Music", os.path.join(home, "Music")),
        ("Pictures", os.path.join(home, "Pictures")),
        ("Videos", os.path.join(home, "Videos")),
    ]
    roots = []
    seen = set()
    for name, path in definitions:
        path = os.path.abspath(os.path.expandvars(path))
        key = os.path.normcase(path)
        if key in seen or not os.path.isdir(path):
            continue
        seen.add(key)
        roots.append(
            {
                "id": _opaque_id("user_root", path),
                "name": name,
                "path": path,
                "kind": "user_root",
            }
        )
    return roots


def discover_entries(roots):
    entries = []
    for root in roots:
        try:
            children = sorted(
                Path(root["path"]).iterdir(),
                key=lambda item: item.name.casefold(),
            )
        except OSError:
            continue
        for child in children:
            try:
                is_dir = child.is_dir()
                is_file = child.is_file()
            except OSError:
                continue
            if not (is_dir or is_file):
                continue
            entries.append(
                {
                    "id": _opaque_id("folder_entry", str(child)),
                    "name": child.name[:200],
                    "path": str(child),
                    "kind": "folder" if is_dir else "file",
                    "root_id": root["id"],
                }
            )
            if len(entries) >= MAX_ENTRIES:
                return entries
    return entries


def _valid_folder_name(value):
    value = str(value or "").strip()
    if not value or len(value) > 100 or value in {".", ".."}:
        return ""
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        return ""
    if value.endswith((" ", ".")):
        return ""
    return value


def _plan(message, recent_context, roots, entries):
    import tools

    payload = {
        "roots": [
            {"id": item["id"], "name": item["name"]} for item in roots
        ],
        "entries": [
            {
                "id": item["id"],
                "name": item["name"],
                "kind": item["kind"],
                "root_id": item["root_id"],
            }
            for item in entries
        ],
        "recent_context": str(recent_context)[-600:],
        "request": str(message)[:600],
    }
    return tools.run_ai_prompt(
        "prompts/casper_file_action.txt",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        expect_json=True,
        num_ctx=4096,
        num_predict=180,
        think=False,
        model_name="llama3.2:latest",
    )


def _select_root_id(message, recent_context, roots, proposed_root_id=""):
    """Let focused AI select exactly one approved user-root ID."""
    try:
        import tools
    except (ImportError, ModuleNotFoundError):
        return proposed_root_id

    payload = {
        "roots": [{"id": item["id"], "name": item["name"]} for item in roots],
        "recent_context": str(recent_context)[-400:],
        "request": str(message)[:500],
    }
    valid_ids = {item["id"] for item in roots}
    prompt_input = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    for _attempt in range(2):
        raw = tools.run_ai_prompt(
            "prompts/casper_file_root.txt",
            prompt_input,
            expect_json=False,
            num_ctx=1024,
            num_predict=32,
            think=False,
            model_name="llama3.2:latest",
        )
        selected = str(raw or "").strip().strip('"\'')
        if selected in valid_ids:
            return selected
        if selected.upper() == "NONE":
            return ""
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + selected[:80]
    return ""


def execute(message, recent_context):
    roots = discover_user_roots()
    entries = discover_entries(roots)
    plan = _plan(message, recent_context, roots, entries)
    if not isinstance(plan, dict):
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "我没有可靠地理解要操作哪个文件或文件夹，可以说得更具体一点吗？",
            "reason": "File-action AI returned invalid structured output.",
        }
    action = str(plan.get("action") or "").upper().strip()
    roots_by_id = {item["id"]: item for item in roots}
    entries_by_id = {item["id"]: item for item in entries}

    if action == "LIST_FOLDER":
        root_id = _select_root_id(
            message,
            recent_context,
            roots,
            proposed_root_id=plan.get("root_id"),
        )
        root = roots_by_id.get(root_id)
        if not root:
            return _clarify()
        items = [
            {"name": item["name"], "kind": item["kind"]}
            for item in entries
            if item["root_id"] == root["id"]
        ][:100]
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "listed_folder",
            "folder": root["name"],
            "count": len(items),
            "items": items,
        }

    if action == "OPEN_PATH":
        candidate_id = str(plan.get("candidate_id") or "")
        target = entries_by_id.get(candidate_id) or roots_by_id.get(candidate_id)
        if not target:
            return _clarify()
        if sys.platform != "win32":
            return _failed("Local path opening is available only on Windows.")
        try:
            os.startfile(target["path"])
        except OSError as error:
            return _failed("Opening the selected path failed: " + str(error)[:240])
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "opened_path",
            "name": target["name"],
            "kind": target["kind"],
        }

    if action == "CREATE_FOLDER":
        root_id = _select_root_id(
            message,
            recent_context,
            roots,
            proposed_root_id=plan.get("root_id"),
        )
        root = roots_by_id.get(root_id)
        folder_name = _valid_folder_name(plan.get("folder_name"))
        if not root or not folder_name:
            return _clarify()
        target = os.path.abspath(os.path.join(root["path"], folder_name))
        common = os.path.commonpath([root["path"], target])
        if os.path.normcase(common) != os.path.normcase(root["path"]):
            return _failed("The requested folder is outside the approved root.")
        try:
            os.mkdir(target)
        except FileExistsError:
            return _failed("A file or folder with that name already exists.")
        except OSError as error:
            return _failed("Creating the folder failed: " + str(error)[:240])
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "created_folder",
            "folder": root["name"],
            "name": folder_name,
        }

    if action == "CLARIFY":
        return _clarify()

    return {
        "success": False,
        "needs_clarification": False,
        "unsupported": True,
        "reason": "This file action is not supported in Phase 13.0.",
    }


def _clarify():
    return {
        "success": False,
        "needs_clarification": True,
        "clarification": "你想操作哪个文件或文件夹？",
        "reason": "AI did not select one valid bounded path ID.",
    }


def _failed(reason):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": False,
        "action": "failed",
        "reason": reason,
    }
