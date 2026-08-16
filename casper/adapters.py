"""Compatibility adapters between Casper and Bekki's stable V1/V2 tools."""

import json


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
