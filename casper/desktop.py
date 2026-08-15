# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""User-triggered, single-shot desktop capture for Bekki Vision."""

import os
import tempfile
import ctypes
from datetime import datetime

from PIL import Image, ImageGrab


MAX_CAPTURE_SIZE = (1600, 1000)


def _capture_path(file_name="current_screen.jpg"):
    capture_dir = os.path.join(tempfile.gettempdir(), "Bekki")
    os.makedirs(capture_dir, exist_ok=True)
    return os.path.join(capture_dir, file_name)


def clear_capture():
    try:
        capture_dir = os.path.dirname(_capture_path())
        for file_name in (
            "current_screen.jpg",
            "current_screen.png",
            "current_window.jpg",
            "current_snip.jpg",
            "current_snip_raw.png",
        ):
            capture_path = os.path.join(capture_dir, file_name)
            if os.path.exists(capture_path):
                os.remove(capture_path)
    except OSError as error:
        print("[DESKTOP CAPTURE CLEANUP]", repr(error))


def capture_screen():
    """Capture and optimise the primary display after an explicit click."""
    capture_path = _capture_path()

    try:
        # One display is both more private and much cheaper for a local Vision
        # model than feeding it an unscaled multi-monitor canvas.
        image = ImageGrab.grab(all_screens=False).convert("RGB")
        original_size = image.size
        image.thumbnail(MAX_CAPTURE_SIZE, Image.Resampling.LANCZOS)
        image.save(
            capture_path,
            format="JPEG",
            quality=82,
            optimize=True,
        )
    except Exception as error:
        return {
            "success": False,
            "file_name": None,
            "file_path": None,
            "captured_at": None,
            "error": str(error),
        }

    return {
        "success": True,
        "file_name": "Desktop screen",
        "file_path": capture_path,
        "original_size": original_size,
        "vision_size": image.size,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _active_window_info():
    if os.name != "nt":
        raise RuntimeError("Active-window capture currently requires Windows.")

    user32 = ctypes.windll.user32
    window_handle = user32.GetForegroundWindow()
    if not window_handle:
        raise RuntimeError("No active window was found.")
    if user32.IsIconic(window_handle):
        raise RuntimeError("The active window is minimized.")

    title_length = user32.GetWindowTextLengthW(window_handle)
    title_buffer = ctypes.create_unicode_buffer(title_length + 1)
    user32.GetWindowTextW(window_handle, title_buffer, title_length + 1)
    title = title_buffer.value.strip() or "Active window"

    rectangle = _Rect()
    # DWM gives the visible frame and avoids the invisible resize border.
    try:
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            window_handle,
            9,  # DWMWA_EXTENDED_FRAME_BOUNDS
            ctypes.byref(rectangle),
            ctypes.sizeof(rectangle),
        )
    except Exception:
        result = -1

    if result != 0 and not user32.GetWindowRect(window_handle, ctypes.byref(rectangle)):
        raise RuntimeError("The active window bounds could not be read.")

    bounds = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise RuntimeError("The active window has an invalid size.")

    return title, bounds


def capture_active_window():
    """Capture only the foreground Windows application."""
    capture_path = _capture_path("current_window.jpg")

    try:
        title, bounds = _active_window_info()
        image = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
        original_size = image.size
        image.thumbnail(MAX_CAPTURE_SIZE, Image.Resampling.LANCZOS)
        image.save(capture_path, format="JPEG", quality=84, optimize=True)
    except Exception as error:
        return {
            "success": False,
            "file_name": None,
            "file_path": None,
            "captured_at": None,
            "error": str(error),
        }

    return {
        "success": True,
        "file_name": title,
        "file_path": capture_path,
        "original_size": original_size,
        "vision_size": image.size,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }


def start_screen_snip():
    """Open Windows' trusted region-selection screenshot overlay."""
    if os.name != "nt":
        return {"success": False, "error": "Screen snipping currently requires Windows."}

    try:
        os.startfile("ms-screenclip:")
        return {"success": True, "error": None}
    except Exception as error:
        return {"success": False, "error": str(error)}


def capture_clipboard_image():
    """Return a selected Windows snip once it reaches the clipboard."""
    try:
        image = ImageGrab.grabclipboard()
    except Exception as error:
        return {"success": False, "pending": False, "error": str(error)}

    if not isinstance(image, Image.Image):
        return {"success": False, "pending": True, "error": None}

    capture_path = _capture_path("current_snip.jpg")
    try:
        image = image.convert("RGB")
        original_size = image.size
        image.thumbnail(MAX_CAPTURE_SIZE, Image.Resampling.LANCZOS)
        image.save(capture_path, format="JPEG", quality=86, optimize=True)
    except Exception as error:
        return {"success": False, "pending": False, "error": str(error)}

    return {
        "success": True,
        "pending": False,
        "file_name": "Selected screenshot",
        "file_path": capture_path,
        "original_size": original_size,
        "vision_size": image.size,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }


def capture_qt_clipboard_image(qimage):
    """Fallback for Windows clipboard formats Pillow cannot decode."""
    raw_path = _capture_path("current_snip_raw.png")
    capture_path = _capture_path("current_snip.jpg")

    try:
        if qimage is None or qimage.isNull():
            return {"success": False, "pending": True, "error": None}
        if not qimage.save(raw_path, "PNG"):
            raise RuntimeError("Qt could not save the clipboard image.")

        with Image.open(raw_path) as source:
            image = source.convert("RGB")
        original_size = image.size
        image.thumbnail(MAX_CAPTURE_SIZE, Image.Resampling.LANCZOS)
        image.save(capture_path, format="JPEG", quality=86, optimize=True)
    except Exception as error:
        return {"success": False, "pending": False, "error": str(error)}
    finally:
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except OSError:
            pass

    return {
        "success": True,
        "pending": False,
        "file_name": "Selected screenshot",
        "file_path": capture_path,
        "original_size": original_size,
        "vision_size": image.size,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "error": None,
    }