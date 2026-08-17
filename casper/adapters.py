"""Compatibility adapters between Casper and Bekki's stable V1/V2 tools."""

import json


def _render_listed_folder(action_result):
    """Render trusted structured folder evidence without generative rewriting."""
    folder = str(action_result.get("folder") or "文件夹")
    items = action_result.get("items")
    if not isinstance(items, list):
        items = []
    if not items:
        return folder + " 文件夹目前是空的。"
    lines = [folder + " 文件夹里有 " + str(len(items)) + " 项："]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = "文件夹" if item.get("kind") == "folder" else "文件"
        lines.append("- " + name + "（" + kind + "）")
    return "\n".join(lines)


def _render_recycle_bin(action_result):
    """Render trusted read-only Recycle Bin evidence exactly once."""
    items = action_result.get("items")
    if not isinstance(items, list):
        items = []
    if not items:
        return "回收站目前是空的。"
    lines = ["回收站里有 " + str(len(items)) + " 项："]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        details = []
        location = str(item.get("original_location") or "").strip()
        deleted = str(item.get("date_deleted") or "").strip()
        if location:
            details.append("原位置：" + location)
        if deleted:
            details.append("删除时间：" + deleted)
        suffix = "（" + "；".join(details) + "）" if details else ""
        lines.append("- " + name + suffix)
    if action_result.get("truncated"):
        lines.append("- 仅显示前 100 项")
    return "\n".join(lines)


def _render_window_control(action_result):
    window = str(action_result.get("window") or "所选窗口")
    control = str(action_result.get("control") or "")
    verbs = {
        "FOCUS_WINDOW": "已切换到",
        "MINIMIZE_WINDOW": "已最小化",
        "MAXIMIZE_WINDOW": "已最大化",
        "RESTORE_WINDOW": "已还原",
    }
    return verbs.get(control, "已操作") + " " + window + "。"


def execute_mode(
    message,
    melchior_plan,
    calibration,
    recent_context,
    status_callback,
):
    mode = melchior_plan["response_mode"]
    search_result = None
    action_context = None

    if mode == "LOCAL_ANSWER":
        return search_result, action_context

    if mode == "TASK_ACTION":
        import task_ai
        import tasks

        status_callback("正在理解任务… ✅")
        task_plan = task_ai.plan_task_action(message, recent_context)
        task_result = tasks.execute_task_plan(task_plan)
        print("[CASPER TASK RESULT]", json.dumps(task_result, ensure_ascii=False))
        action_context = (
            "CASPER TASK ACTION RESULT\n"
            "This is the authoritative result from Bekki's local Task system.\n"
            "Do not change, contradict, or invent its task data.\n\n"
            + json.dumps(task_result, ensure_ascii=False, indent=2)
            + "\n\nIf needs_clarification is true, ask exactly one concise "
            "clarifying question. Do not claim the task was saved unless "
            "success is true."
        )
        return search_result, action_context

    if mode == "DEVICE_ACTION":
        from . import device_actions

        status_callback("Casper 正在执行设备操作… 🧭")
        action_result = device_actions.execute_user_request(
            message,
            recent_context,
            elevation_approved=bool(
                melchior_plan.get("device_elevation_approved", False)
            ),
            device_approval=melchior_plan.get("device_action_approval"),
        )
        print(
            "[CASPER DEVICE RESULT]",
            json.dumps(action_result, ensure_ascii=False),
        )
        action_context = (
            "CASPER DEVICE ACTION RESULT\n"
            "This is the authoritative result of the supervised local action.\n"
            "Do not claim an application opened unless success is true.\n"
            "For a requested game, success/completed must be true and action "
            "must be game_opened before saying the game opened or wishing the "
            "user fun. launcher_opened is incomplete even though the launcher "
            "window is visible.\n"
            "Use the AI post-launch verification status as the result. If action "
            "is launcher_opened, state that only the launcher opened. If action "
            "is uncertain, say the observed state is uncertain. Never claim the "
            "game itself started without game_opened.\n"
            "If needs_clarification is true, ask the supplied clarification "
            "question concisely. For system_control_completed or "
            "window_control_completed, state only the control actually "
            "reported as completed. For file actions, describe only the "
            "bounded folder/path operation reported by the result. Never say "
            "a path was opened or a folder was created unless success and "
            "completed are both true. For listed_folder, name the folder and "
            "show the returned items (or state that the returned list is "
            "empty). If the reported folder differs from the requested one, "
            "state that mismatch; never turn a local device action into a web "
            "search or suggest a search pending_action.\n\n"
            + json.dumps(action_result, ensure_ascii=False, indent=2)
        )
        if (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "listed_folder"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_listed_folder(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "listed_recycle_bin"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_recycle_bin(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "opened_recycle_bin"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已打开回收站。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "restored_recycle_item"
        ):
            name = str(action_result.get("name") or "该项目")
            location = str(action_result.get("original_location") or "")
            suffix = "，原位置：" + location if location else ""
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已恢复 " + name + suffix + "。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "window_control_completed"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_window_control(action_result),
            }
        if action_result.get("requires_approval"):
            from .safety import reflex

            approval_type = str(
                action_result.get("approval_type") or "permission_escalation"
            )
            handoff = reflex(
                approval_type,
                action_result.get("application") or action_result.get("name", ""),
            ) or {}
            pending = handoff.get("pending_approval", {})
            pending.update(
                {
                    "resume_after_user_confirmation": True,
                    "original_request": message,
                    "handoff_type": "device_action_approval",
                    "approval_payload": {
                        "action": action_result.get("action"),
                        "candidate_id": action_result.get("candidate_id"),
                        "name": action_result.get("name"),
                        "original_location": action_result.get("original_location"),
                    },
                }
            )
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": pending,
            }
        return search_result, action_context

    # Load the existing search/browser layer only for research modes.
    import tools

    if mode == "SOCIAL_RESEARCH":
        search_result = tools.social_research_controller(
            message,
            melchior_plan.get("social_platforms", []),
            status_callback=status_callback,
        )
        return search_result, action_context

    if mode in {"SHOPPING_RESEARCH", "RECOMMENDATION_RESEARCH"}:
        from . import browser as casper_browser
        from . import recommendation

        try:
            domain = melchior_plan.get("recommendation_domain") or "PRODUCT"
            if domain == "PRODUCT" and mode == "SHOPPING_RESEARCH":
                search_result = casper_browser.shopping_research_controller(
                    message,
                    recent_context,
                    status_callback=status_callback,
                )
                if isinstance(search_result, dict):
                    search_result["recommendation_domain"] = "PRODUCT"
            else:
                search_result = recommendation.research_controller(
                    message,
                    domain,
                    calibration,
                    recent_context,
                    status_callback=status_callback,
                )
        except Exception as error:
            print("[CASPER RECOMMENDATION BROWSER UNAVAILABLE]", repr(error))
            search_result = {"status": "BROWSER_UNAVAILABLE", "results": []}

        return search_result, action_context

    status_callback("正在整理搜索问题… 🔍")

    if mode == "NEWS_FEED":
        queries = tools.build_news_queries(message, recent_context)
        from . import browser as casper_browser

        try:
            search_result = casper_browser.news_feed_controller(
                queries,
                user_request=message,
                status_callback=status_callback,
            )
        except Exception as error:
            print("[CASPER NEWS BROWSER UNAVAILABLE]", repr(error))
            search_result = {"status": "BROWSER_UNAVAILABLE", "results": []}

    elif mode == "FACT_LOOKUP":
        query = tools.build_search_query(message, recent_context)
        from . import browser as casper_browser

        try:
            search_result = casper_browser.fact_lookup_controller(
                query,
                user_request=message,
                status_callback=status_callback,
            )
        except Exception as error:
            print("[CASPER BROWSER UNAVAILABLE]", repr(error))
            search_result = {"status": "BROWSER_UNAVAILABLE", "results": []}

    elif mode == "CLAIM_CHECK":
        query = tools.build_claim_query(
            melchior_plan.get("claim_to_verify") or message
        )
        search_result = tools.search_controller(
            query,
            status_callback=status_callback,
        )

    return search_result, action_context


def execute_pending_search(query, status_callback):
    import tools

    return tools.search_controller(query, status_callback)


def list_pending_tasks():
    import tasks

    task_data = tasks.load_tasks()
    pending = [
        task
        for task in task_data.get("tasks", [])
        if task.get("status") == "pending"
    ]
    pending.sort(key=lambda task: task.get("due_at", ""))
    return pending


def _task_ui_action(action, task_id, reason):
    import tasks

    return tasks.execute_task_plan(
        {
            "action": action,
            "task_id": task_id,
            "task_reference": None,
            "title": "",
            "due_at": None,
            "recurrence": "NONE",
            "clarification": None,
            "reason": reason,
        }
    )


def complete_task(task_id):
    return _task_ui_action(
        "COMPLETE",
        task_id,
        "User completed the task through the Task UI.",
    )


def delete_task(task_id, confirmed=False):
    if not confirmed:
        return {
            "success": False,
            "needs_confirmation": True,
            "message": "Task deletion requires confirmation.",
        }
    return _task_ui_action(
        "DELETE",
        task_id,
        "User confirmed task deletion through the Task UI.",
    )


def poll_due_notifications():
    import tasks

    return tasks.pop_due_notifications()


def clear_desktop_capture():
    import desktop

    return desktop.clear_capture()


def capture_screen():
    import desktop

    return desktop.capture_screen()


def capture_active_window():
    import desktop

    return desktop.capture_active_window()


def start_screen_snip():
    import desktop

    return desktop.start_screen_snip()


def capture_clipboard_image():
    import desktop

    return desktop.capture_clipboard_image()


def capture_qt_clipboard_image(qimage):
    import desktop

    return desktop.capture_qt_clipboard_image(qimage)
