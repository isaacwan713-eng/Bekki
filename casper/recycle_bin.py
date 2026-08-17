"""Read-only Windows Recycle Bin actions selected by AI."""

import json
import hashlib
import os
import subprocess
import sys
import time


MAX_ITEMS = 100


def _item_id(item):
    value = "\0".join(
        str(item.get(key) or "")
        for key in ("shell_path", "name", "original_location", "date_deleted")
    )
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _plan(message, recent_context):
    import tools

    return tools.run_ai_prompt(
        "prompts/casper_recycle_bin.txt",
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


def _classify_restore_intent(message, recent_context):
    """Focused AI judgment: restore one item versus every other recycle action."""
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
                "prompts/casper_recycle_restore_intent.txt",
                prompt_input,
                expect_json=False,
                num_ctx=1024,
                num_predict=12,
                think=False,
                model_name="llama3.2:latest",
            )
        except (ImportError, ModuleNotFoundError):
            return None
        value = str(raw or "").strip().upper()
        if value in {"RESTORE_ITEM", "NOT_RESTORE"}:
            return value
        prompt_input += "\nINVALID_PREVIOUS_OUTPUT:\n" + value[:80]
    return ""


def _select_item_id(message, recent_context, items):
    import tools

    catalog = [
        {
            "id": item["id"],
            "name": item["name"],
            "original_location": item.get("original_location", ""),
            "date_deleted": item.get("date_deleted", ""),
        }
        for item in items
    ]
    prompt_input = json.dumps(
        {
            "items": catalog,
            "recent_context": str(recent_context)[-600:],
            "request": str(message)[:500],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    valid_ids = {item["id"] for item in items}
    for _attempt in range(2):
        raw = tools.run_ai_prompt(
            "prompts/casper_recycle_item.txt",
            prompt_input,
            expect_json=False,
            num_ctx=2048,
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


def _discover_items():
    if sys.platform != "win32":
        raise OSError("Recycle Bin inspection is available only on Windows.")
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$s=New-Object -ComObject Shell.Application;"
        "$f=$s.Namespace(10);"
        "$r=@($f.Items()|Select-Object -First 100|ForEach-Object{"
        "[pscustomobject]@{name=[string]$_.Name;"
        "shell_path=[string]$_.Path;"
        "original_location=[string]($_.ExtendedProperty('System.Recycle.DeletedFrom'));"
        "date_deleted=[string]($_.ExtendedProperty('System.Recycle.DateDeleted'));"
        "size=[string]($_.ExtendedProperty('System.Size'))}});"
        "$r|ConvertTo-Json -Compress"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=flags,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError((completed.stderr or "Recycle Bin query failed.")[:300])
    text = (completed.stdout or "").strip()
    if not text:
        return []
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    items = []
    for item in parsed[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:240]
        if not name:
            continue
        item_data = {
            "name": name,
            "shell_path": str(item.get("shell_path") or "").strip()[:1000],
            "original_location": str(
                item.get("original_location") or ""
            ).strip()[:500],
            "date_deleted": str(item.get("date_deleted") or "").strip()[:100],
            "size": str(item.get("size") or "").strip()[:100],
        }
        item_data["id"] = _item_id(item_data)
        items.append(item_data)
    return items


def _open_recycle_bin():
    if sys.platform != "win32":
        raise OSError("Recycle Bin opening is available only on Windows.")
    subprocess.Popen(
        ["explorer.exe", "shell:RecycleBinFolder"],
        close_fds=True,
    )


def _restore_item(item):
    if sys.platform != "win32":
        raise OSError("Recycle Bin restore is available only on Windows.")
    shell_path = str(item.get("shell_path") or "")
    if not shell_path:
        raise OSError("The selected Recycle Bin item has no current shell path.")
    script = (
        "$s=New-Object -ComObject Shell.Application;"
        "$f=$s.Namespace(10);"
        "$i=@($f.Items()|Where-Object{$_.Path -eq $env:BEKKI_RECYCLE_ITEM_PATH}"
        "|Select-Object -First 1);"
        "if($i.Count -ne 1){exit 4};"
        "$i[0].InvokeVerb('RESTORE')"
    )
    environment = os.environ.copy()
    environment["BEKKI_RECYCLE_ITEM_PATH"] = shell_path
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=flags,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError((completed.stderr or "Recycle Bin restore failed.")[:300])


def _restore_completed(candidate_id, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current_ids = {item["id"] for item in _discover_items()}
        if candidate_id not in current_ids:
            return True
        time.sleep(0.5)
    return False


def execute(message, recent_context, approval=None):
    if (
        isinstance(approval, dict)
        and approval.get("action") == "restore_recycle_item"
    ):
        action = "RESTORE_RECYCLE_ITEM"
    else:
        restore_intent = _classify_restore_intent(message, recent_context)
        if restore_intent == "RESTORE_ITEM":
            action = "RESTORE_RECYCLE_ITEM"
        elif restore_intent in {"NOT_RESTORE", None}:
            action = str(_plan(message, recent_context) or "").strip().upper()
        else:
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "你是想恢复回收站中的一个项目吗？",
                "reason": "Focused restore-intent AI returned invalid output twice.",
            }
    if action == "LIST_RECYCLE_BIN":
        try:
            items = _discover_items()
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            return _failed("Reading the Recycle Bin failed: " + str(error)[:300])
        public_items = [
            {key: value for key, value in item.items() if key != "shell_path"}
            for item in items
        ]
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "listed_recycle_bin",
            "count": len(items),
            "items": public_items,
            "truncated": len(items) >= MAX_ITEMS,
        }
    if action == "OPEN_RECYCLE_BIN":
        try:
            _open_recycle_bin()
        except (OSError, subprocess.SubprocessError) as error:
            return _failed("Opening the Recycle Bin failed: " + str(error)[:300])
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "opened_recycle_bin",
        }
    if action == "RESTORE_RECYCLE_ITEM":
        try:
            items = _discover_items()
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            return _failed("Reading the Recycle Bin failed: " + str(error)[:300])
        by_id = {item["id"]: item for item in items}
        approved_id = ""
        if isinstance(approval, dict) and approval.get("action") == "restore_recycle_item":
            approved_id = str(approval.get("candidate_id") or "")
        if approved_id:
            selected = by_id.get(approved_id)
            if not selected:
                return _failed("The approved Recycle Bin item is no longer present.")
            try:
                _restore_item(selected)
            except (OSError, subprocess.SubprocessError) as error:
                return _failed("Restoring the selected item failed: " + str(error)[:300])
            try:
                restored = _restore_completed(approved_id)
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
                return _failed("Restore verification failed: " + str(error)[:300])
            if not restored:
                return _failed(
                    "Windows accepted the restore action, but the item remained in the Recycle Bin."
                )
            return {
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "restored_recycle_item",
                "name": selected["name"],
                "original_location": selected.get("original_location", ""),
            }
        selected_id = _select_item_id(message, recent_context, items)
        selected = by_id.get(selected_id)
        if not selected:
            return {
                "success": False,
                "needs_clarification": True,
                "clarification": "你想恢复回收站里的哪一个项目？",
                "reason": "AI did not select one current Recycle Bin item ID.",
            }
        return {
            "success": False,
            "completed": False,
            "needs_clarification": False,
            "requires_approval": True,
            "approval_type": "recycle_restore",
            "action": "restore_recycle_item",
            "candidate_id": selected["id"],
            "name": selected["name"],
            "original_location": selected.get("original_location", ""),
            "reason": "Restoring a Recycle Bin item requires user confirmation.",
        }
    if action == "CLARIFY":
        return {
            "success": False,
            "needs_clarification": True,
            "clarification": "你想查看回收站、打开窗口，还是恢复其中一个项目？",
            "reason": "Recycle Bin AI requested clarification.",
        }
    return {
        "success": False,
        "needs_clarification": False,
        "unsupported": True,
        "reason": "Delete and empty Recycle Bin are not supported in Phase 15.0.",
    }


def _failed(reason):
    return {
        "success": False,
        "completed": False,
        "needs_clarification": False,
        "action": "failed",
        "reason": reason,
    }
