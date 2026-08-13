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
        with open(LOG_FILE, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _last_successful_run():
    for log in reversed(_load_logs()):
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
    last_run = _last_successful_run()
    if last_run is None:
        return True, None

    elapsed_days = (datetime.now(timezone.utc) - last_run).total_seconds() / 86400
    return elapsed_days >= interval_days, elapsed_days


def run_if_due(interval_days=DEFAULT_INTERVAL_DAYS, force=False):
    os.chdir(PROJECT_DIRECTORY)
    due, elapsed_days = learning_is_due(interval_days)

    if not force and not due:
        print(
            "[KNOWLEDGE SCHEDULER] Not due; last successful cycle was "
            + f"{elapsed_days:.1f} days ago."
        )
        return 0

    print("[KNOWLEDGE SCHEDULER] Starting autonomous learning cycle.")
    try:
        import knowledge_worker

        knowledge_worker.run_learning_cycle()
        return 0
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
    print("Actual learning interval:", interval_days, "days")
    print("Python:", sys.executable)


def show_status():
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is only available on Windows.")

    subprocess.run(
        ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
        check=False,
    )
    due, elapsed_days = learning_is_due()
    print("Knowledge learning due:", due)
    if elapsed_days is not None:
        print("Days since last successful cycle:", round(elapsed_days, 1))


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
    elif args.command == "uninstall":
        uninstall_task()


if __name__ == "__main__":
    main()