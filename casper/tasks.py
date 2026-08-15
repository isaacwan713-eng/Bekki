# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Deterministic local task and reminder storage for Bekki."""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta


VALID_ACTIONS = {
    "CREATE",
    "LIST",
    "COMPLETE",
    "DELETE",
    "NONE",
}

VALID_RECURRENCES = {
    "NONE",
    "DAILY",
    "WEEKLY",
    "MONTHLY",
}

MAX_TASKS = 500


def _tasks_path():
    base_dir = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.abspath(".")
    )

    data_dir = os.path.join(
        base_dir,
        "data",
    )

    os.makedirs(
        data_dir,
        exist_ok=True,
    )

    return os.path.join(
        data_dir,
        "tasks.json",
    )


def _now():
    return datetime.now().astimezone()


def _new_store():
    return {
        "version": 1,
        "tasks": [],
    }


def load_tasks():
    path = _tasks_path()

    if not os.path.exists(path):
        return _new_store()

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

    except (
        OSError,
        json.JSONDecodeError,
    ) as error:
        print(
            "[TASKS] load failed:",
            repr(error),
        )
        return _new_store()

    if not isinstance(data, dict):
        return _new_store()

    task_items = data.get("tasks", [])

    if not isinstance(task_items, list):
        task_items = []

    task_items = [
        item
        for item in task_items
        if isinstance(item, dict)
    ]

    return {
        "version": 1,
        "tasks": task_items[-MAX_TASKS:],
    }


def save_tasks(task_data):
    path = _tasks_path()
    temporary_path = path + ".tmp"

    safe_data = {
        "version": 1,
        "tasks": task_data.get(
            "tasks",
            [],
        )[-MAX_TASKS:],
    }

    try:
        with open(
            temporary_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                safe_data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temporary_path,
            path,
        )

    except OSError as error:
        print(
            "[TASKS] save failed:",
            repr(error),
        )
        raise


def _parse_due_at(value):
    if not isinstance(value, str):
        return None

    value = value.strip()

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None

    # Task AI must provide an explicit timezone.
    if parsed.tzinfo is None:
        return None

    return parsed


def normalize_plan(plan):
    """Validate the structure returned by Task AI."""

    if not isinstance(plan, dict):
        return {
            "action": "NONE",
            "task_id": None,
            "task_reference": None,
            "title": "",
            "due_at": None,
            "recurrence": "NONE",
            "clarification": (
                "I could not understand the task request."
            ),
            "reason": "Invalid task plan.",
        }

    action = str(
        plan.get(
            "action",
            "NONE",
        )
    ).upper().strip()

    if action not in VALID_ACTIONS:
        action = "NONE"

    recurrence = str(
        plan.get(
            "recurrence",
            "NONE",
        )
    ).upper().strip()

    if recurrence not in VALID_RECURRENCES:
        recurrence = "NONE"

    task_id = str(
        plan.get("task_id") or ""
    ).strip()[:64]

    task_reference = str(
        plan.get("task_reference") or ""
    ).strip()[:160]

    title = str(
        plan.get("title") or ""
    ).strip()[:240]

    due_at = str(
        plan.get("due_at") or ""
    ).strip()

    clarification = str(
        plan.get("clarification") or ""
    ).strip()[:500]

    reason = str(
        plan.get("reason") or ""
    ).strip()[:280]

    return {
        "action": action,
        "task_id": task_id or None,
        "task_reference": (
            task_reference or None
        ),
        "title": title,
        "due_at": due_at or None,
        "recurrence": recurrence,
        "clarification": (
            clarification or None
        ),
        "reason": reason,
    }


def _find_task(task_data, plan):
    pending_tasks = [
        item
        for item in task_data["tasks"]
        if item.get("status") == "pending"
    ]

    task_id = plan.get("task_id")

    if task_id:
        for task in pending_tasks:
            if task.get("id") == task_id:
                return task

    reference = (
        plan.get("task_reference")
        or plan.get("title")
        or ""
    ).casefold().strip()

    if not reference:
        return None

    matching_tasks = [
        task
        for task in pending_tasks
        if reference in str(
            task.get(
                "title",
                "",
            )
        ).casefold()
    ]

    if len(matching_tasks) == 1:
        return matching_tasks[0]

    return None


def execute_task_plan(plan):
    """Execute a validated Task AI plan."""

    plan = normalize_plan(plan)
    task_data = load_tasks()
    action = plan["action"]

    if plan.get("clarification"):
        return {
            "success": False,
            "needs_clarification": True,
            "message": plan["clarification"],
        }

    if action == "CREATE":
        due_at = _parse_due_at(
            plan.get("due_at")
        )

        if not plan["title"]:
            return {
                "success": False,
                "needs_clarification": True,
                "message": (
                    "The task needs a clear title."
                ),
            }

        if due_at is None:
            return {
                "success": False,
                "needs_clarification": True,
                "message": (
                    "The task needs an unambiguous "
                    "date, time, and timezone."
                ),
            }

        if due_at <= _now():
            return {
                "success": False,
                "needs_clarification": True,
                "message": (
                    "That reminder time is already "
                    "in the past. Ask the user for "
                    "a future time."
                ),
            }

        task = {
            "id": uuid.uuid4().hex,
            "title": plan["title"],
            "due_at": due_at.isoformat(),
            "recurrence": plan["recurrence"],
            "status": "pending",
            "created_at": _now().isoformat(),
            "completed_at": None,
            "last_notified_at": None,
        }

        task_data["tasks"].append(task)
        task_data["tasks"] = (
            task_data["tasks"][-MAX_TASKS:]
        )

        save_tasks(task_data)

        return {
            "success": True,
            "action": "CREATE",
            "task": task,
        }

    if action == "LIST":
        pending_tasks = [
            task
            for task in task_data["tasks"]
            if task.get("status") == "pending"
        ]

        pending_tasks.sort(
            key=lambda task: task.get(
                "due_at",
                "",
            )
        )

        return {
            "success": True,
            "action": "LIST",
            "tasks": pending_tasks[:50],
            "count": len(pending_tasks),
        }

    if action in {
        "COMPLETE",
        "DELETE",
    }:
        task = _find_task(
            task_data,
            plan,
        )

        if task is None:
            return {
                "success": False,
                "needs_clarification": True,
                "message": (
                    "No single pending task matched "
                    "that description. Ask the user "
                    "which task they mean."
                ),
            }

        if action == "COMPLETE":
            task["status"] = "completed"
            task["completed_at"] = (
                _now().isoformat()
            )

        else:
            task_data["tasks"] = [
                item
                for item in task_data["tasks"]
                if item.get("id")
                != task.get("id")
            ]

        save_tasks(task_data)

        return {
            "success": True,
            "action": action,
            "task": task,
        }

    return {
        "success": False,
        "needs_clarification": True,
        "message": (
            "The requested task action is unclear."
        ),
    }


def _next_month(value):
    if value.month == 12:
        next_year = value.year + 1
        next_month = 1

    else:
        next_year = value.year
        next_month = value.month + 1

    month_lengths = [
        31,
        (
            29
            if (
                next_year % 4 == 0
                and (
                    next_year % 100 != 0
                    or next_year % 400 == 0
                )
            )
            else 28
        ),
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]

    next_day = min(
        value.day,
        month_lengths[next_month - 1],
    )

    return value.replace(
        year=next_year,
        month=next_month,
        day=next_day,
    )


def pop_due_notifications(now=None):
    """Return reminders that have become due.

    One-time reminders are marked as notified.
    Repeating reminders are moved to their next due time.
    """

    current_time = now or _now()
    task_data = load_tasks()
    due_tasks = []
    changed = False

    for task in task_data["tasks"]:
        if task.get("status") != "pending":
            continue

        if task.get("last_notified_at"):
            continue

        due_at = _parse_due_at(
            task.get("due_at")
        )

        if due_at is None:
            continue

        if due_at > current_time:
            continue

        due_tasks.append(
            dict(task)
        )

        recurrence = task.get(
            "recurrence",
            "NONE",
        )

        if recurrence == "NONE":
            task["last_notified_at"] = (
                current_time.isoformat()
            )
            changed = True
            continue

        if recurrence == "DAILY":
            interval = timedelta(days=1)

        elif recurrence == "WEEKLY":
            interval = timedelta(days=7)

        else:
            interval = None

        if recurrence == "MONTHLY":
            next_due_at = _next_month(
                due_at
            )

        else:
            next_due_at = (
                due_at + interval
            )

        # If Bekki was closed for several cycles,
        # jump to the next future occurrence.
        while next_due_at <= current_time:
            if recurrence == "MONTHLY":
                next_due_at = _next_month(
                    next_due_at
                )

            else:
                next_due_at += interval

        task["due_at"] = (
            next_due_at.isoformat()
        )
        task["last_notified_at"] = None
        changed = True

    if changed:
        save_tasks(task_data)

    return due_tasks