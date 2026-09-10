"""Install and run Bekki's autonomous Knowledge learning schedule on Windows."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


TASK_NAME = "Bekki Knowledge Learning"
DEFAULT_INTERVAL_DAYS = 30
DEFAULT_CHECK_TIME = "10:00"
PROJECT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_DIRECTORY, "data", "learning_logs.json")


def _load_logs():
    try:
        import knowledge

        return knowledge.load_learning_logs()
    except Exception:
        # The Knowledge API already fails open to the JSON mirror. Retain this
        # final scheduler guard so a damaged log never prevents a learning run.
        return []


def _last_successful_run():
    import knowledge_autonomy

    for log in reversed(_load_logs()):
        if not knowledge_autonomy.is_successful_run(log):
            continue
        timestamp = log.get("finished_at")
        if not timestamp:
            continue
        try:
            value = datetime.fromisoformat(timestamp)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value
        except (TypeError, ValueError):
            continue
    return None


def learning_is_due(interval_days=DEFAULT_INTERVAL_DAYS):
    import knowledge_worker

    due, _plan = knowledge_worker.autonomy_due(
        background_interval_days=interval_days,
    )
    last_run = _last_successful_run()
    elapsed_days = None
    if last_run is not None:
        elapsed_days = (
            datetime.now(timezone.utc) - last_run
        ).total_seconds() / 86400
    return due, elapsed_days


def run_if_due(interval_days=DEFAULT_INTERVAL_DAYS, force=False):
    os.chdir(PROJECT_DIRECTORY)
    try:
        import knowledge_worker

        result = knowledge_worker.run_autonomy_cycle(
            trigger="windows_scheduler",
            background_interval_days=interval_days,
            force=force,
        )
        status = str(result.get("status") or "FAILED").upper()
        print(
            "[KNOWLEDGE SCHEDULER RESULT]",
            "status=" + status,
            "reason=" + str(result.get("reason") or "none"),
        )
        return 1 if status == "FAILED" else 0
    except Exception as error:
        # Scheduler failures are logged without changing Knowledge data.
        os.makedirs(os.path.join(PROJECT_DIRECTORY, "data"), exist_ok=True)
        error_path = os.path.join(
            PROJECT_DIRECTORY,
            "data",
            "knowledge_scheduler_errors.log",
        )
        with open(error_path, "a", encoding="utf-8") as file:
            file.write(
                datetime.now(timezone.utc).isoformat()
                + " | "
                + repr(error)
                + "\n"
            )
        print("[KNOWLEDGE SCHEDULER ERROR]", repr(error))
        return 1


def _task_command(interval_days):
    python_path = os.path.abspath(sys.executable)
    scheduler_path = os.path.abspath(__file__)
    return (
        '"'
        + python_path
        + '" "'
        + scheduler_path
        + '" run --interval-days '
        + str(interval_days)
    )


def install_task(check_time, interval_days):
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")

    command = [
        "schtasks.exe",
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        _task_command(interval_days),
        "/SC",
        "DAILY",
        "/ST",
        check_time,
        "/F",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    print("[KNOWLEDGE SCHEDULER] Installed:", TASK_NAME)
    print("Daily check time:", check_time)
    print("Profile fallback interval:", interval_days, "days")
    print("Lifecycle refreshes: checked daily when due")
    print("Python:", sys.executable)


def show_plan():
    import knowledge_worker

    due, plan = knowledge_worker.autonomy_due()
    last_run = _last_successful_run()
    elapsed_days = None
    if last_run is not None:
        elapsed_days = (
            datetime.now(timezone.utc) - last_run
        ).total_seconds() / 86400
    print("Knowledge learning due:", due)
    print("Selection mode:", plan.get("mode"))
    print("Selected topic IDs:", plan.get("selected_topic_ids", []))
    print("Next eligible due:", plan.get("next_due_at"))
    if elapsed_days is not None:
        print("Days since last successful cycle:", round(elapsed_days, 1))


def show_status():
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")

    subprocess.run(
        ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
        check=False,
    )
    show_plan()


def uninstall_task():
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")

    result = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    print("[KNOWLEDGE SCHEDULER] Removed:", TASK_NAME)


def main():
    parser = argparse.ArgumentParser(description="Bekki Knowledge Scheduler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install")
    install.add_argument("--time", default=DEFAULT_CHECK_TIME)
    install.add_argument(
        "--interval-days",
        type=int,
        default=DEFAULT_INTERVAL_DAYS,
    )

    run = subparsers.add_parser("run")
    run.add_argument(
        "--interval-days",
        type=int,
        default=DEFAULT_INTERVAL_DAYS,
    )
    run.add_argument("--force", action="store_true")

    subparsers.add_parser("status")
    subparsers.add_parser("plan")
    subparsers.add_parser("uninstall")

    args = parser.parse_args()
    if args.command == "install":
        if args.interval_days < 1:
            parser.error("--interval-days must be at least 1")
        install_task(args.time, args.interval_days)
    elif args.command == "run":
        if args.interval_days < 1:
            parser.error("--interval-days must be at least 1")
        raise SystemExit(run_if_due(args.interval_days, args.force))
    elif args.command == "status":
        show_status()
    elif args.command == "plan":
        show_plan()
    elif args.command == "uninstall":
        uninstall_task()


if __name__ == "__main__":
    main()
