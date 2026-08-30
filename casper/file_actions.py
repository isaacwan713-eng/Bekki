"""Bounded user-folder actions selected by AI and enforced by Python."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time


MAX_ENTRIES = 240
MAX_SEARCH_ENTRIES = 200000
MAX_SEARCH_MATCHES = 50
MAX_SEARCH_SECONDS = 10.0

VALID_FILE_ACTIONS = {
    "LIST_FOLDER",
    "SEARCH_FILES",
    "OPEN_PATH",
    "CREATE_FOLDER",
    "UNSUPPORTED",
    "CLARIFY",
}


_FILE_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "LIST_FOLDER",
                "SEARCH_FILES",
                "OPEN_PATH",
                "CREATE_FOLDER",
                "UNSUPPORTED",
                "CLARIFY",
            ],
        },
        "root_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "candidate_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
        "folder_name": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
        "query": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "match_mode": {
            "anyOf": [
                {"type": "string", "enum": ["EXACT_NAME", "CONTAINS_NAME"]},
                {"type": "null"},
            ]
        },
        "target_kind": {
            "anyOf": [
                {"type": "string", "enum": ["FILE", "FOLDER", "ANY"]},
                {"type": "null"},
            ]
        },
        "reason": {"type": "string"},
    },
    "required": [
        "action",
        "root_id",
        "candidate_id",
        "folder_name",
        "query",
        "match_mode",
        "target_kind",
        "reason",
    ],
    "additionalProperties": False,
}


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


def discover_search_roots():
    """Use the local user profile as the bounded recursive-search surface."""
    home = os.path.abspath(
        os.path.expandvars(os.environ.get("USERPROFILE") or str(Path.home()))
    )
    if os.path.isdir(home):
        return [
            {
                "id": _opaque_id("search_root", home),
                "name": "用户目录",
                "path": home,
                "kind": "search_root",
            }
        ]
    return discover_user_roots()


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

    authoritative_action = _classify_file_action(message, recent_context)
    if not authoritative_action:
        return None

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
        "authoritative_file_action": authoritative_action,
    }
    prompt_input = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    plan_schema = copy.deepcopy(_FILE_PLAN_SCHEMA)
    plan_schema["properties"]["action"]["enum"] = [authoritative_action]
    attempts = (
        ("gemma4:e4b", 4096, 240),
        ("gemma4:12b", 4096, 280),
    )
    raw = None
    for attempt, (model_name, num_ctx, num_predict) in enumerate(attempts):
        retry_input = prompt_input
        if attempt:
            retry_input += (
                "\nThe previous planner output was invalid. Independently "
                "return one complete schema-valid file-action JSON object."
            )
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_file_action.txt",
                retry_input,
                expect_json=True,
                num_ctx=num_ctx,
                num_predict=num_predict,
                think=False,
                model_name=model_name,
                json_schema=plan_schema,
            )
        except Exception as error:
            print("[FILE ACTION PLANNER ERROR]", model_name, repr(error))
            continue
        finally:
            _release_model(tools, model_name)
        if (
            isinstance(raw, dict)
            and str(raw.get("action") or "").upper().strip()
            == authoritative_action
        ):
            return raw
        print("[FILE ACTION PLANNER INVALID]", model_name, repr(raw))
    return raw


def _release_model(tools_module, model_name):
    try:
        tools_module.unload_model(model_name)
        print("[FILE ACTION MODEL RELEASED]", model_name)
    except Exception as error:
        print("[FILE ACTION MODEL RELEASE WARNING]", model_name, repr(error))


def _classify_file_action(message, recent_context):
    """Let reliable AI choose the file action before detailed extraction."""
    import tools

    prompt_input = (
        "RECENT_CONTEXT_FOR_REFERENCE_ONLY:\n"
        + str(recent_context)[-400:]
        + "\nCURRENT_REQUEST:\n"
        + str(message)[:600]
    )
    for model_name in ("gemma4:12b", "gemma4:e4b"):
        try:
            raw = tools.run_ai_prompt(
                "prompts/casper_file_action_gate.txt",
                prompt_input,
                expect_json=False,
                num_ctx=2048,
                num_predict=32,
                think=False,
                model_name=model_name,
            )
        except Exception as error:
            print("[FILE ACTION GATE ERROR]", model_name, repr(error))
            continue
        finally:
            _release_model(tools, model_name)
        value = str(raw or "").strip().strip('"\'').upper()
        if value in VALID_FILE_ACTIONS:
            print("[FILE ACTION GATE]", value)
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _valid_search_query(value):
    """Accept one literal filename/folder-name fragment, never a path/glob."""
    value = str(value or "").strip()
    if not value or len(value) > 200 or value in {".", ".."}:
        return ""
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value):
        return ""
    return value


def _hidden_or_reparse(path):
    """Keep recursive search out of hidden/system/reparse-point trees."""
    if Path(path).name.startswith(".") or Path(path).is_symlink():
        return True
    try:
        attributes = int(getattr(os.stat(path, follow_symlinks=False), "st_file_attributes", 0))
    except OSError:
        return True
    return bool(attributes & 0x406)


def search_user_files(roots, query, match_mode, target_kind):
    """Search bounded user roots and return only paths observed on disk."""
    needle = query.casefold()
    started = time.monotonic()
    matches = []
    scanned_entries = 0
    truncated = False

    def name_matches(name):
        candidate = name.casefold()
        if match_mode == "EXACT_NAME":
            return candidate == needle
        return needle in candidate

    for root in roots:
        root_path = os.path.abspath(root["path"])
        for current, directories, files in os.walk(
            root_path, topdown=True, followlinks=False
        ):
            directories[:] = [
                name
                for name in directories
                if not _hidden_or_reparse(os.path.join(current, name))
            ]
            visible_files = [
                name
                for name in files
                if not _hidden_or_reparse(os.path.join(current, name))
            ]
            scanned_entries += len(directories) + len(visible_files)

            candidates = []
            if target_kind in {"FOLDER", "ANY"}:
                candidates.extend((name, "folder") for name in directories)
            if target_kind in {"FILE", "ANY"}:
                candidates.extend((name, "file") for name in visible_files)
            for name, kind in candidates:
                if not name_matches(name):
                    continue
                observed_path = os.path.abspath(os.path.join(current, name))
                try:
                    common = os.path.commonpath([root_path, observed_path])
                except ValueError:
                    continue
                if os.path.normcase(common) != os.path.normcase(root_path):
                    continue
                matches.append(
                    {
                        "id": _opaque_id("search_result", observed_path),
                        "name": name[:200],
                        "path": observed_path,
                        "kind": kind,
                        "root": root["name"],
                    }
                )
                if len(matches) >= MAX_SEARCH_MATCHES:
                    truncated = True
                    break

            if (
                truncated
                or scanned_entries >= MAX_SEARCH_ENTRIES
                or time.monotonic() - started >= MAX_SEARCH_SECONDS
            ):
                truncated = True
                break
        if truncated:
            break

    return {
        "matches": matches,
        "scanned_entries": scanned_entries,
        "truncated": truncated,
    }


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

    if action == "SEARCH_FILES":
        query = _valid_search_query(plan.get("query"))
        match_mode = str(plan.get("match_mode") or "").upper().strip()
        target_kind = str(plan.get("target_kind") or "").upper().strip()
        if (
            not query
            or match_mode not in {"EXACT_NAME", "CONTAINS_NAME"}
            or target_kind not in {"FILE", "FOLDER", "ANY"}
        ):
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": (
                    "请告诉我要查找的完整文件名或文件夹名，例如 test.txt。"
                ),
                "reason": "File-search AI did not supply one safe literal name.",
            }
        search_roots = discover_search_roots()
        if not search_roots:
            return _failed("No approved user folders were available to search.")
        search = search_user_files(
            search_roots, query, match_mode, target_kind
        )
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "searched_files",
            "query": query,
            "match_mode": match_mode,
            "target_kind": target_kind,
            "scope": [root["name"] for root in search_roots],
            "count": len(search["matches"]),
            "matches": search["matches"],
            "scanned_entries": search["scanned_entries"],
            "truncated": search["truncated"],
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
