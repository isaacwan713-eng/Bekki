"""One bounded scheduler for every autonomous Bekki Knowledge source.

The desktop idle timer and Windows Task Scheduler both call the same worker.
This module owns deterministic topic priority, cooldowns, and the cross-process
run lock; it never decides whether a fact is true or writes a Knowledge claim.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import tempfile
import threading


AUTONOMY_CONTRACT_VERSION = 1
DEFAULT_BACKGROUND_INTERVAL_DAYS = 30
ACTIVE_GAP_COOLDOWN_DAYS = 7
DUE_REFRESH_COOLDOWN_HOURS = 24
NO_EVIDENCE_RETRY_HOURS = 24
FAILED_RETRY_HOURS = 1
MAX_SELECTED_TOPICS = 1

_THREAD_LOCK = threading.Lock()
_PROJECT_KEY = hashlib.sha256(
    str(Path(__file__).resolve().parent).casefold().encode("utf-8")
).hexdigest()[:16]
_WINDOWS_MUTEX_NAME = (
    "Local\\BekkiKnowledgeAutonomyV1_" + _PROJECT_KEY
)
_LOCK_FILE = os.path.join(
    tempfile.gettempdir(),
    "bekki_knowledge_autonomy_" + _PROJECT_KEY + ".lock",
)


def _utc(value=None):
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _utc(parsed)


def _evidence_count(log):
    """Count outcomes that prove the cycle reached readable claim evidence."""

    total = 0
    for key in ("verified", "updated", "duplicate", "log_only"):
        try:
            total += max(0, int(log.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return total


def effective_run_status(log):
    """Normalize old V1.10.54 zero-evidence completions without rewriting."""

    if not isinstance(log, dict):
        return "INVALID"
    status = str(log.get("status") or "COMPLETED").upper().strip()
    try:
        contract_version = int(log.get("autonomy_contract_version") or 0)
    except (TypeError, ValueError):
        contract_version = 0
    if (
        contract_version >= 1
        and status in {"COMPLETED", "COMPLETED_WITH_ERRORS"}
        and "verified" in log
        and _evidence_count(log) == 0
    ):
        return "NO_VERIFIED_EVIDENCE"
    return status


def is_successful_run(log):
    """Accept legacy successful logs but reject explicit no-evidence runs."""

    return (
        isinstance(log, dict)
        and _parse_time(log.get("finished_at")) is not None
        and effective_run_status(log) in {
            "COMPLETED", "COMPLETED_WITH_ERRORS"
        }
    )


def last_successful_run(logs):
    values = [
        _parse_time(log.get("finished_at"))
        for log in logs or []
        if is_successful_run(log)
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _last_topic_attempt(logs, topic_id):
    topic_id = str(topic_id or "").strip().lower()
    values = []
    for log in logs or []:
        if not isinstance(log, dict):
            continue
        selected = {
            str(value or "").strip().lower()
            for value in log.get("selected_topic_ids", [])
        }
        if topic_id not in selected:
            continue
        timestamp = _parse_time(log.get("finished_at"))
        if timestamp is not None:
            values.append((timestamp, effective_run_status(log)))
    return max(values, key=lambda value: value[0]) if values else (None, None)


def _last_background_attempt(logs):
    values = []
    for log in logs or []:
        if not isinstance(log, dict):
            continue
        if str(log.get("selection_mode") or "").upper() != "BACKGROUND_PROFILE":
            continue
        timestamp = _parse_time(log.get("finished_at"))
        if timestamp is not None:
            values.append((timestamp, effective_run_status(log)))
    return max(values, key=lambda value: value[0]) if values else (None, None)


def _attempt_cooldown(status, wake_reason):
    status = str(status or "").upper()
    if status == "NO_VERIFIED_EVIDENCE":
        return timedelta(hours=NO_EVIDENCE_RETRY_HOURS)
    if status == "FAILED":
        return timedelta(hours=FAILED_RETRY_HOURS)
    if str(wake_reason or "").upper() in {
        "REVIEW_DUE", "AUTO_INTEREST_REFRESH"
    }:
        return timedelta(hours=DUE_REFRESH_COOLDOWN_HOURS)
    return timedelta(days=ACTIVE_GAP_COOLDOWN_DAYS)


def _cooldown_elapsed(logs, topic_id, wake_reason, now):
    previous, status = _last_topic_attempt(logs, topic_id)
    if previous is None:
        return True
    cooldown = _attempt_cooldown(status, wake_reason)
    return now - previous >= cooldown


def _topic_retry_due(logs, topic_id, wake_reason):
    previous, status = _last_topic_attempt(logs, topic_id)
    if previous is None:
        return None
    return previous + _attempt_cooldown(status, wake_reason)


def _topic_row(topic, wake_reason, due_at=None):
    topic = topic if isinstance(topic, dict) else {}
    lifecycle = topic.get("lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    aliases = []
    for raw in topic.get("aliases", []):
        value = " ".join(str(raw or "").split())[:120]
        if value and value.casefold() not in {
            item.casefold() for item in aliases
        }:
            aliases.append(value)
    title = " ".join(str(topic.get("title") or "").split())[:200]
    topic_id = str(topic.get("topic_id") or "").strip().lower()[:80]
    try:
        interest_score = float(lifecycle.get("interest_score") or 0.0)
    except (TypeError, ValueError):
        interest_score = 0.0
    return {
        "topic_id": topic_id,
        "title": title,
        "aliases": aliases[:12],
        "classification": (
            topic.get("classification")
            if isinstance(topic.get("classification"), dict) else {}
        ),
        "lifecycle_state": str(lifecycle.get("state") or "").upper()[:40],
        "interest_score": max(0.0, min(1.0, interest_score)),
        "next_focus": " ".join(
            str(lifecycle.get("next_focus") or "").split()
        )[:500],
        "wake_reason": str(wake_reason or "").upper()[:60],
        "due_at": str(due_at or "")[:80] or None,
    }


def build_plan(
    topic_catalog,
    refresh_candidates,
    learning_logs,
    *,
    now=None,
    background_interval_days=DEFAULT_BACKGROUND_INTERVAL_DAYS,
    force=False,
    excluded_topic_ids=None,
):
    """Select one lifecycle-owned topic or a bounded profile fallback."""

    current = _utc(now)
    excluded = {
        str(value or "").strip().lower()
        for value in excluded_topic_ids or []
        if str(value or "").strip()
    }
    catalog = {
        str(topic.get("topic_id") or "").strip().lower(): topic
        for topic in topic_catalog or []
        if isinstance(topic, dict) and str(topic.get("topic_id") or "").strip()
    }
    candidates = []
    lifecycle_retry_due = []
    refresh_by_id = {
        str(item.get("topic_id") or "").strip().lower(): item
        for item in refresh_candidates or []
        if isinstance(item, dict) and str(item.get("topic_id") or "").strip()
    }
    for topic_id, refresh in refresh_by_id.items():
        if topic_id in excluded or topic_id not in catalog:
            continue
        wake_reason = str(refresh.get("wake_reason") or "REVIEW_DUE").upper()
        if not force and not _cooldown_elapsed(
            learning_logs, topic_id, wake_reason, current
        ):
            retry_due = _topic_retry_due(
                learning_logs, topic_id, wake_reason
            )
            if retry_due is not None:
                lifecycle_retry_due.append(retry_due)
            continue
        row = _topic_row(catalog[topic_id], wake_reason, refresh.get("due_at"))
        if row["lifecycle_state"] != "PAUSED_COMPLETE":
            continue
        candidates.append((0, row))

    for topic_id, topic in catalog.items():
        if topic_id in excluded or topic_id in refresh_by_id:
            continue
        lifecycle = topic.get("lifecycle")
        lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
        if (
            str(lifecycle.get("state") or "").upper() != "ACTIVE"
            or not str(lifecycle.get("next_focus") or "").strip()
        ):
            continue
        if not force and not _cooldown_elapsed(
            learning_logs, topic_id, "OPEN_GAP", current
        ):
            retry_due = _topic_retry_due(
                learning_logs, topic_id, "OPEN_GAP"
            )
            if retry_due is not None:
                lifecycle_retry_due.append(retry_due)
            continue
        candidates.append((1, _topic_row(topic, "OPEN_GAP")))

    candidates.sort(key=lambda pair: (
        pair[0],
        -pair[1]["interest_score"],
        str(pair[1].get("due_at") or ""),
        pair[1]["topic_id"],
    ))
    if candidates:
        selected = [pair[1] for pair in candidates[:MAX_SELECTED_TOPICS]]
        mode = selected[0]["wake_reason"]
        return {
            "contract_version": AUTONOMY_CONTRACT_VERSION,
            "due": True,
            "mode": mode,
            "selected_topics": selected,
            "selected_topic_ids": [item["topic_id"] for item in selected],
            "reason": (
                "A lifecycle-owned topic is due; urgency is ranked before "
                "interest and only one topic may run."
            ),
            "planned_at": current.isoformat(),
            "next_due_at": None,
        }

    if lifecycle_retry_due and not force:
        next_retry = min(lifecycle_retry_due)
        return {
            "contract_version": AUTONOMY_CONTRACT_VERSION,
            "due": False,
            "mode": "NOT_DUE",
            "selected_topics": [],
            "selected_topic_ids": [],
            "reason": (
                "A lifecycle Topic is in its bounded retry cooldown; the "
                "profile fallback cannot bypass that cooldown."
            ),
            "planned_at": current.isoformat(),
            "next_due_at": next_retry.isoformat(),
        }

    try:
        interval_days = max(1, int(background_interval_days))
    except (TypeError, ValueError):
        interval_days = DEFAULT_BACKGROUND_INTERVAL_DAYS
    last_run = last_successful_run(learning_logs)
    next_due = (
        last_run + timedelta(days=interval_days)
        if last_run is not None else current
    )
    background_due = force or last_run is None or current >= next_due
    if background_due and not force:
        previous, previous_status = _last_background_attempt(learning_logs)
        if previous is not None and previous_status in {
            "NO_VERIFIED_EVIDENCE", "FAILED"
        }:
            retry_due = previous + _attempt_cooldown(
                previous_status,
                "BACKGROUND_PROFILE",
            )
            if current < retry_due:
                background_due = False
                next_due = max(next_due, retry_due)
    return {
        "contract_version": AUTONOMY_CONTRACT_VERSION,
        "due": background_due,
        "mode": "BACKGROUND_PROFILE" if background_due else "NOT_DUE",
        "selected_topics": [],
        "selected_topic_ids": [],
        "reason": (
            "No lifecycle topic is eligible; run one profile-guided fallback."
            if background_due else
            "No lifecycle topic is eligible and the profile fallback is not due."
        ),
        "planned_at": current.isoformat(),
        "next_due_at": next_due.isoformat(),
    }


@contextmanager
def cycle_lock():
    """Yield False instead of blocking when another process owns the cycle."""

    if not _THREAD_LOCK.acquire(blocking=False):
        yield False
        return
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = (
                wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR
            )
            create_mutex.restype = wintypes.HANDLE
            wait = kernel32.WaitForSingleObject
            wait.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            wait.restype = wintypes.DWORD
            release = kernel32.ReleaseMutex
            release.argtypes = (wintypes.HANDLE,)
            release.restype = wintypes.BOOL
            close = kernel32.CloseHandle
            close.argtypes = (wintypes.HANDLE,)
            close.restype = wintypes.BOOL

            handle = create_mutex(None, False, _WINDOWS_MUTEX_NAME)
            if not handle:
                raise OSError(
                    ctypes.get_last_error(),
                    "Could not create Knowledge autonomy mutex",
                )
            acquired = False
            try:
                acquired = wait(handle, 0) in (0x00000000, 0x00000080)
                yield acquired
            finally:
                if acquired:
                    release(handle)
                close(handle)
            return

        handle = open(_LOCK_FILE, "a+b")
        try:
            try:
                import fcntl
            except ImportError:
                yield True
                return
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
    finally:
        _THREAD_LOCK.release()
