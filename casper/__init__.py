"""Casper: Bekki's supervised execution and tool-control core."""

from .core import execute, execute_pending_search
from .adapters import (
    capture_active_window,
    capture_clipboard_image,
    capture_qt_clipboard_image,
    capture_screen,
    clear_desktop_capture,
    complete_task,
    delete_task,
    list_pending_tasks,
    poll_due_notifications,
    start_screen_snip,
)

__all__ = [
    "execute",
    "execute_pending_search",
    "capture_active_window",
    "capture_clipboard_image",
    "capture_qt_clipboard_image",
    "capture_screen",
    "clear_desktop_capture",
    "complete_task",
    "delete_task",
    "list_pending_tasks",
    "poll_due_notifications",
    "start_screen_snip",
]

