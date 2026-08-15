# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""AI semantic planner for Bekki tasks and reminders."""

import json
from datetime import datetime

import localization as i18n
import tasks
import tools


def plan_task_action(
    user_message,
    recent_context="",
):
    """Ask the local AI to interpret one task request.

    AI decides the user's semantic intent.
    Python later validates and executes the plan.
    """

    current_time = (
        datetime.now().astimezone()
    )

    task_data = tasks.load_tasks()

    pending_tasks = [
        task
        for task in task_data.get(
            "tasks",
            [],
        )
        if task.get("status") == "pending"
    ]

    input_text = (
        "Current local datetime:\n"
        + current_time.isoformat()
        + "\n\nCurrent timezone:\n"
        + str(current_time.tzinfo)
        + "\n\nSystem language:\n"
        + i18n.ai_language_context()
        + "\n\nCurrent pending tasks:\n"
        + json.dumps(
            pending_tasks[:50],
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nRecent conversation:\n"
        + recent_context
        + "\n\nCurrent user message:\n"
        + user_message
    )

    raw_plan = tools.run_ai_prompt(
        "prompts/task_action.txt",
        input_text,
        expect_json=True,
        num_ctx=4096,
        num_predict=420,
    )

    plan = tasks.normalize_plan(
        raw_plan
    )

    print(
        "[TASK PLAN]",
        json.dumps(
            plan,
            ensure_ascii=False,
        ),
    )

    return plan