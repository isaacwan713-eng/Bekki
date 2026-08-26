"""Bounded Windows UI Automation adapter for the ChatGPT desktop app.

The adapter never uses coordinates and never invents an answer.  It sends an
already-governed prompt only after locating a visible ChatGPT input control,
then reads a completed answer from an exposed Copy control or stable UIA text.
If the main window does not expose its composer, the adapter may open the
official ChatGPT Companion Window with Alt+Space.  It still never uses web
fallback or screen coordinates.
"""

from collections import Counter
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


MAX_OUTBOUND_PROMPT = 5000
MAX_EXTERNAL_ANSWER = 12000
APP_NAMES = {"chatgpt", "chatgpt desktop"}
LOGIN_LABELS = {
    "log in", "login", "sign in", "sign up", "登录", "登錄", "注册",
}
COPY_LABELS = {"copy", "copy response", "复制", "複製"}
STOP_LABELS = {
    "stop", "stop generating", "stop streaming", "停止", "停止生成",
}
INPUT_HINTS = (
    "ask chatgpt", "message chatgpt", "send a message", "prompt",
    "ask anything", "type a message", "chat input", "composer",
    "询问 chatgpt", "詢問 chatgpt", "给 chatgpt 发消息",
    "給 chatgpt 發消息", "输入消息", "輸入消息",
)
NON_INPUT_HINTS = (
    "composer utility bar", "utility bar", "toolbar", "tool bar",
    "工具栏", "工具列",
)
IGNORED_TEXT = {
    "chatgpt", "new chat", "library", "projects", "scheduled", "plugins",
    "more", "recents", "chat", "work", "copy", "share", "edit",
    "新建聊天", "新對話", "复制", "複製", "分享", "编辑", "編輯",
}
USER_MESSAGE_PREFIXES = (
    "you said:", "you said", "user said:", "user said",
    "你说：", "你说:", "你说", "您说：", "您说:", "您说",
)
ASSISTANT_MESSAGE_PREFIXES = (
    "chatgpt said:", "chatgpt said", "assistant said:", "assistant said",
    "chatgpt 说：", "chatgpt 说:", "chatgpt 说",
)
PROVIDER_ERROR_PREFIXES = (
    "request failed with status", "something went wrong", "network error",
    "请求失败", "网络错误", "網絡錯誤",
)
MIN_SUBSTANTIVE_ANSWER_CHARS = 4


def _load_uia():
    try:
        from pywinauto import Desktop, keyboard
    except (ImportError, OSError) as error:
        raise RuntimeError("pywinauto is unavailable: " + str(error)) from error
    return Desktop, keyboard


def _process_image_name(process_id):
    """Return the executable basename for one observed window process."""
    if sys.platform != "win32":
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        )
        handle = kernel32.OpenProcess(0x1000, False, int(process_id))
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)
            ):
                return ""
            return Path(buffer.value).name.casefold()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def _safe_call(control, method, default=None):
    try:
        return getattr(control, method)()
    except Exception:
        return default


def _control_name(control):
    name = str(_safe_call(control, "window_text", "") or "").strip()
    if name:
        return name
    try:
        return str(control.element_info.name or "").strip()
    except Exception:
        return ""


def _automation_id(control):
    try:
        return str(control.element_info.automation_id or "").strip()
    except Exception:
        return ""


def _is_usable(control):
    return bool(
        _safe_call(control, "is_visible", False)
        and _safe_call(control, "is_enabled", False)
    )


def _is_chatgpt_window(window):
    title = _control_name(window).casefold()
    if "chatgpt" not in title:
        return False
    try:
        image = _process_image_name(window.process_id())
    except Exception:
        image = ""
    if image in {"msedge.exe", "chrome.exe", "firefox.exe", "brave.exe"}:
        return False
    return image.startswith("chatgpt") or image in {
        "applicationframehost.exe", "webviewhost.exe"
    }


def _desktop_windows(Desktop):
    try:
        return list(Desktop(backend="uia").windows())
    except Exception:
        return []


def _chatgpt_windows(Desktop, visible_only=False):
    matches = [
        window for window in _desktop_windows(Desktop)
        if _is_chatgpt_window(window)
    ]
    if visible_only:
        matches = [
            window for window in matches
            if _safe_call(window, "is_visible", False)
        ]
    return matches


def _find_chatgpt_window(Desktop):
    matches = _chatgpt_windows(Desktop)
    for window in reversed(matches):
        if _safe_call(window, "is_visible", False):
            return window
    return matches[-1] if matches else None


def _start_apps():
    if sys.platform != "win32":
        return []
    command = (
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = json.loads(completed.stdout.strip() or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    if isinstance(value, dict):
        value = [value]
    return value if isinstance(value, list) else []


def _chatgpt_app_id():
    candidates = []
    for item in _start_apps():
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("name") or "").strip()
        app_id = str(item.get("AppID") or item.get("app_id") or "").strip()
        normalized = name.casefold()
        if app_id and (normalized in APP_NAMES or normalized.startswith("chatgpt")):
            candidates.append((name, app_id))
    exact = [item for item in candidates if item[0].casefold() == "chatgpt"]
    selected = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
    return selected[1] if selected else ""


def _launch_app(app_id):
    if not app_id or sys.platform != "win32":
        return False
    try:
        subprocess.Popen(
            ["explorer.exe", "shell:AppsFolder\\" + str(app_id)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("[EXTERNAL AI DESKTOP LAUNCHED] ChatGPT")
        return True
    except OSError as error:
        print("[EXTERNAL AI DESKTOP LAUNCH WARNING]", repr(error))
        return False


def _focus_window(window):
    try:
        window.restore()
    except Exception:
        pass
    try:
        window.set_focus()
        return True
    except Exception as error:
        print("[EXTERNAL AI DESKTOP FOCUS WARNING]", repr(error))
        return False


def _descendants(window, control_type):
    try:
        return list(window.descendants(control_type=control_type))
    except Exception:
        return []


def _find_prompt_control(window):
    controls = _descendants(window, "Edit")
    controls += _descendants(window, "Document")
    controls += _descendants(window, "Custom")
    controls += _descendants(window, "Group")
    try:
        window_rect = window.rectangle()
        window_bottom = int(window_rect.bottom)
        window_top = int(window_rect.top)
        window_width = max(1, int(window_rect.width()))
    except Exception:
        window_bottom = 0
        window_top = 0
        window_width = 1
    scored = []
    for index, control in enumerate(controls):
        if not _is_usable(control):
            continue
        name = _control_name(control).casefold()
        automation_id = _automation_id(control).casefold()
        if any(word in name for word in ("search", "搜索", "搜尋")):
            continue
        # Some ChatGPT Desktop WebView builds expose the attachment/model/voice
        # button row as "Composer utility bar". It is a toolbar container, not
        # the editable message surface, even though its name contains composer.
        if any(hint in name or hint in automation_id for hint in NON_INPUT_HINTS):
            continue
        score = 0
        if any(hint in name for hint in INPUT_HINTS):
            score += 120
        if any(hint in automation_id for hint in ("prompt", "composer", "message")):
            score += 100
        try:
            rect = control.rectangle()
            threshold = window_top + ((window_bottom - window_top) * 0.62)
            if window_bottom and int(rect.bottom) >= threshold:
                score += 30
            if int(rect.width()) >= window_width * 0.28:
                score += 20
        except Exception:
            pass
        control_type = str(
            getattr(getattr(control, "element_info", None), "control_type", "")
        )
        if control_type == "Edit":
            score += 10
        elif not (
            any(hint in name for hint in INPUT_HINTS)
            or any(hint in automation_id for hint in ("prompt", "composer", "message"))
        ):
            continue
        if score:
            scored.append((score, index, control))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]))
    selected = scored[-1][2]
    print(
        "[EXTERNAL AI DESKTOP INPUT]",
        _control_name(selected)[:120] or _automation_id(selected)[:120],
    )
    return selected


def _window_handle(window):
    try:
        return int(window.handle)
    except Exception:
        return 0


def _foreground_window_handle():
    if sys.platform != "win32":
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.argtypes = ()
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def _activate_window_handle(handle):
    if sys.platform != "win32" or not handle:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetForegroundWindow.argtypes = (ctypes.c_void_p,)
        user32.SetForegroundWindow.restype = wintypes.BOOL
        return bool(user32.SetForegroundWindow(ctypes.c_void_p(int(handle))))
    except Exception:
        return False


def _window_area(window):
    try:
        rectangle = window.rectangle()
        return max(0, int(rectangle.width())) * max(0, int(rectangle.height()))
    except Exception:
        return 0


def _accessibility_counts(window):
    counts = {
        control_type: len(_descendants(window, control_type))
        for control_type in ("Edit", "Document", "Custom", "Group", "Button", "Text")
    }
    print(
        "[EXTERNAL AI DESKTOP UIA]",
        " ".join(key + "=" + str(value) for key, value in counts.items()),
    )


def _wait_for_prompt(Desktop, preferred_window, timeout_seconds=15):
    """Wait for the WebView accessibility tree instead of racing app startup."""
    deadline = time.time() + max(1, float(timeout_seconds))
    last_window = preferred_window
    while time.time() < deadline:
        windows = _chatgpt_windows(Desktop, visible_only=True)
        ordered = []
        if preferred_window is not None:
            ordered.append(preferred_window)
        ordered.extend(window for window in reversed(windows) if window is not preferred_window)
        for window in ordered:
            last_window = window
            control = _find_prompt_control(window)
            if control is not None:
                return window, control, "READY"
        for window in ordered:
            if _login_required(window):
                return window, None, "LOGIN_REQUIRED"
        time.sleep(0.5)
    if last_window is not None:
        _accessibility_counts(last_window)
    return last_window, None, "NOT_FOUND"


def _open_companion(Desktop, keyboard, main_window, timeout_seconds=10):
    """Open the official Companion Window and return only verified app UI."""
    visible_before = _chatgpt_windows(Desktop, visible_only=True)
    handles_before = {_window_handle(window) for window in visible_before}
    main_area = _window_area(main_window)
    if not _focus_window(main_window):
        return None, None, "NOT_OPENED"
    try:
        keyboard.send_keys("%{SPACE}", pause=0.05)
    except Exception as error:
        print("[EXTERNAL AI COMPANION WARNING]", repr(error))
        return None, None, "NOT_OPENED"
    print("[EXTERNAL AI COMPANION REQUESTED] Alt+Space")

    deadline = time.time() + max(1, float(timeout_seconds))
    confirmed = None
    while time.time() < deadline:
        windows = _chatgpt_windows(Desktop, visible_only=True)
        for window in reversed(windows):
            handle = _window_handle(window)
            area = _window_area(window)
            is_new = bool(handle and handle not in handles_before)
            is_smaller_peer = bool(
                handle
                and handle != _window_handle(main_window)
                and main_area
                and area
                and area < main_area * 0.85
            )
            if is_new or is_smaller_peer:
                confirmed = window
                control = _find_prompt_control(window)
                if control is not None:
                    print("[EXTERNAL AI COMPANION READY] uia_input")
                    return window, control, "READY"
        # The main app can finish exposing its composer while the shortcut is
        # being handled. That remains an ordinary verified-control send.
        control = _find_prompt_control(main_window)
        if control is not None:
            return main_window, control, "READY"
        time.sleep(0.4)
    if confirmed is not None:
        _focus_window(confirmed)
        _accessibility_counts(confirmed)
        print("[EXTERNAL AI COMPANION READY] focused_only")
        return confirmed, None, "FOCUSED_ONLY"
    return None, None, "NOT_OPENED"


def _button_controls(window, include_hidden=False):
    return [
        control for control in _descendants(window, "Button")
        if include_hidden or _safe_call(control, "is_visible", False)
    ]


def _buttons_named(window, labels, include_hidden=False):
    matches = []
    for control in _button_controls(window, include_hidden=include_hidden):
        name = _control_name(control).casefold().strip()
        if name in labels or any(label in name for label in labels if len(label) > 4):
            matches.append(control)
    return matches


def _login_required(window):
    return bool(_buttons_named(window, LOGIN_LABELS))


def _read_clipboard_text():
    if sys.platform != "win32":
        return ""
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = (wintypes.UINT,)
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = ()
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    for _attempt in range(8):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.04)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return str(ctypes.wstring_at(pointer) or "")
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _write_clipboard_text(text):
    if sys.platform != "win32":
        return False
    from ctypes import wintypes

    value = str(text or "")
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = (wintypes.HWND,)
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = ()
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = ()
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.restype = ctypes.c_void_p
    encoded_size = (len(value) + 1) * ctypes.sizeof(ctypes.c_wchar)
    handle = kernel32.GlobalAlloc(0x0002, encoded_size)  # GMEM_MOVEABLE
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(pointer, ctypes.create_unicode_buffer(value), encoded_size)
    kernel32.GlobalUnlock(handle)
    for _attempt in range(8):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.04)
    else:
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(13, handle):
            kernel32.GlobalFree(handle)
            return False
        handle = None
        return True
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def _type_unicode_text(text):
    """Type exact Unicode with SendInput when the clipboard is unavailable."""
    if sys.platform != "win32":
        return False
    try:
        from ctypes import wintypes

        ULONG_PTR = (
            ctypes.c_ulonglong
            if ctypes.sizeof(ctypes.c_void_p) == 8
            else ctypes.c_ulong
        )

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class INPUT_UNION(ctypes.Union):
            _fields_ = (("ki", KEYBDINPUT),)

        class INPUT(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = (("type", wintypes.DWORD), ("union", INPUT_UNION))

        encoded = str(text or "").encode("utf-16-le")
        code_units = [
            int.from_bytes(chunk, "little")
            for chunk in (
                encoded[index:index + 2]
                for index in range(0, len(encoded), 2)
            )
        ]
        events = []
        for unit in code_units:
            events.append(
                INPUT(type=1, union=INPUT_UNION(ki=KEYBDINPUT(0, unit, 0x0004, 0, 0)))
            )
            events.append(
                INPUT(
                    type=1,
                    union=INPUT_UNION(
                        ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0)
                    ),
                )
            )
        if not events:
            return False
        array_type = INPUT * len(events)
        payload = array_type(*events)
        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        )
        user32.SendInput.restype = wintypes.UINT
        sent = int(user32.SendInput(len(payload), payload, ctypes.sizeof(INPUT)))
        return sent == len(payload)
    except Exception as error:
        print("[EXTERNAL AI DESKTOP UNICODE INPUT WARNING]", repr(error))
        return False


def _accessible_texts(window, include_hidden=False):
    values = []
    for control_type in ("Text", "Document"):
        for control in _descendants(window, control_type):
            if not include_hidden and not _safe_call(control, "is_visible", False):
                continue
            text = _control_name(control).strip()
            if not text or text.casefold() in IGNORED_TEXT or len(text) > 16000:
                continue
            values.append(text)
    return values[-500:]


def _clean_answer_candidate(text, prompt):
    normalized = str(text or "").strip()
    if not normalized or normalized == prompt:
        return ""
    folded = normalized.casefold()
    if folded in IGNORED_TEXT:
        return ""
    if any(folded.startswith(prefix) for prefix in USER_MESSAGE_PREFIXES):
        return ""
    for prefix in ASSISTANT_MESSAGE_PREFIXES:
        if folded.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            folded = normalized.casefold()
            break
    if not normalized or any(folded.startswith(prefix) for prefix in PROVIDER_ERROR_PREFIXES):
        return ""
    if prompt and prompt in normalized and len(normalized) <= len(prompt) + 100:
        return ""
    if len(normalized) < MIN_SUBSTANTIVE_ANSWER_CHARS:
        return ""
    return normalized[:MAX_EXTERNAL_ANSWER]


def _new_text_answer(before, current, prompt):
    remaining = Counter(before)
    fresh = []
    for text in current:
        if remaining[text] > 0:
            remaining[text] -= 1
            continue
        normalized = _clean_answer_candidate(text, prompt)
        if normalized and normalized not in fresh:
            fresh.append(normalized)
    answer = "\n".join(fresh).strip()
    return answer[:MAX_EXTERNAL_ANSWER]


def _invoke_copy_and_read(control):
    try:
        previous = _read_clipboard_text()
    except Exception as error:
        print("[EXTERNAL AI DESKTOP COPY READ WARNING]", repr(error))
        return ""
    sentinel = "BEKKI_EXTERNAL_AI_CLIPBOARD_" + str(time.time_ns())
    try:
        sentinel_written = _write_clipboard_text(sentinel)
    except Exception as error:
        print("[EXTERNAL AI DESKTOP COPY WRITE WARNING]", repr(error))
        return ""
    if not sentinel_written:
        return ""
    try:
        try:
            control.invoke()
        except Exception:
            control.click_input()
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                current = _read_clipboard_text()
            except Exception as error:
                print("[EXTERNAL AI DESKTOP COPY POLL WARNING]", repr(error))
                return ""
            if current and current != sentinel:
                return current.strip()[:MAX_EXTERNAL_ANSWER]
            time.sleep(0.1)
        return ""
    finally:
        try:
            _write_clipboard_text(previous)
        except Exception as error:
            print("[EXTERNAL AI DESKTOP COPY RESTORE WARNING]", repr(error))


def _enter_prompt(control, keyboard, prompt):
    previous = ""
    clipboard_changed = False
    text_entered = False
    try:
        try:
            previous = _read_clipboard_text()
        except Exception as error:
            print("[EXTERNAL AI DESKTOP CLIPBOARD READ WARNING]", repr(error))
        control.set_focus()
        try:
            control.set_edit_text(prompt)
            text_entered = True
            print("[EXTERNAL AI DESKTOP WRITE ROUTE] uia_value")
        except Exception:
            pasted = False
            try:
                if _write_clipboard_text(prompt):
                    clipboard_changed = True
                    keyboard.send_keys("^v", pause=0.03)
                    pasted = True
                    print("[EXTERNAL AI DESKTOP WRITE ROUTE] clipboard")
            except Exception as error:
                print("[EXTERNAL AI DESKTOP CLIPBOARD WRITE WARNING]", repr(error))
            if not pasted:
                if not _type_unicode_text(prompt):
                    return "INPUT_FAILED"
                print("[EXTERNAL AI DESKTOP WRITE ROUTE] unicode_sendinput")
            text_entered = True
        keyboard.send_keys("{ENTER}", pause=0.03)
        return "SENT"
    except Exception as error:
        print("[EXTERNAL AI DESKTOP SEND WARNING]", repr(error))
        return "SEND_UNCERTAIN" if text_entered else "INPUT_FAILED"
    finally:
        if clipboard_changed:
            try:
                _write_clipboard_text(previous)
            except Exception as error:
                print("[EXTERNAL AI DESKTOP CLIPBOARD RESTORE WARNING]", repr(error))


def _enter_focused_companion(keyboard, prompt):
    """Paste only after a distinct ChatGPT Companion Window was observed."""
    previous = _read_clipboard_text()
    try:
        if not _write_clipboard_text(prompt):
            return False
        keyboard.send_keys("^v", pause=0.05)
        keyboard.send_keys("{ENTER}", pause=0.05)
        return True
    except Exception as error:
        print("[EXTERNAL AI COMPANION SEND WARNING]", repr(error))
        return False
    finally:
        _write_clipboard_text(previous)


def _background_after_send(window, previous_foreground):
    """Return focus to Bekki while keeping ChatGPT's WebView readable."""
    chatgpt_handle = _window_handle(window)
    if (
        previous_foreground
        and previous_foreground != chatgpt_handle
        and _activate_window_handle(previous_foreground)
    ):
        print("[EXTERNAL AI DESKTOP BACKGROUND] previous_window_restored")
        return False
    try:
        window.minimize()
        print("[EXTERNAL AI DESKTOP BACKGROUND] minimized_fallback")
        return True
    except Exception as error:
        print("[EXTERNAL AI DESKTOP BACKGROUND WARNING]", repr(error))
        return False


def _minimize_after_read(window, already_minimized):
    if already_minimized:
        return
    try:
        window.minimize()
        print("[EXTERNAL AI DESKTOP BACKGROUND] minimized_after_read")
    except Exception as error:
        print("[EXTERNAL AI DESKTOP BACKGROUND WARNING]", repr(error))


def _wait_for_answer(
    window,
    prompt,
    before_texts,
    before_copy_count,
    timeout_seconds,
    include_hidden=False,
):
    deadline = time.time() + max(15, int(timeout_seconds))
    last_text = ""
    stable_rounds = 0
    while time.time() < deadline:
        copy_controls = _buttons_named(
            window, COPY_LABELS, include_hidden=include_hidden
        )
        generating = bool(
            _buttons_named(window, STOP_LABELS, include_hidden=include_hidden)
        )
        if len(copy_controls) > before_copy_count and not generating:
            copied = _invoke_copy_and_read(copy_controls[-1])
            copied = _clean_answer_candidate(copied, prompt)
            if copied:
                return copied
        current = _new_text_answer(
            before_texts,
            _accessible_texts(window, include_hidden=include_hidden),
            prompt,
        )
        if current and current == last_text:
            stable_rounds += 1
        else:
            last_text = current
            stable_rounds = 0
        if last_text and stable_rounds >= 3 and not generating:
            return last_text
        time.sleep(1)
    return ""


def ask_prompt(outbound_prompt, source_kind="user_explicit", timeout_seconds=180):
    """Ask through ChatGPT Desktop; return evidence without browser fallback."""
    prompt = str(outbound_prompt or "").strip()[:MAX_OUTBOUND_PROMPT]
    if not prompt:
        return {"status": "INVALID_PROMPT", "reason": "No outbound prompt."}
    if sys.platform != "win32":
        return {
            "status": "DESKTOP_UNAVAILABLE",
            "reason": "ChatGPT Desktop automation is available only on Windows.",
            "prompt_sent": False,
        }
    try:
        Desktop, keyboard = _load_uia()
    except RuntimeError as error:
        return {
            "status": "DESKTOP_AUTOMATION_UNAVAILABLE",
            "reason": str(error),
            "prompt_sent": False,
        }
    previous_foreground = _foreground_window_handle()

    window = _find_chatgpt_window(Desktop)
    app_id = ""
    if window is None:
        app_id = _chatgpt_app_id()
        if not app_id:
            return {
                "status": "DESKTOP_APP_NOT_INSTALLED",
                "reason": "ChatGPT Desktop is not installed.",
                "prompt_sent": False,
            }
        if not _launch_app(app_id):
            return {
                "status": "DESKTOP_LAUNCH_FAILED",
                "reason": "ChatGPT Desktop could not be launched.",
                "prompt_sent": False,
            }
        deadline = time.time() + 20
        while time.time() < deadline and window is None:
            time.sleep(0.4)
            window = _find_chatgpt_window(Desktop)
    if window is None:
        return {
            "status": "DESKTOP_WINDOW_NOT_FOUND",
            "reason": "ChatGPT Desktop opened but no controllable window was found.",
            "prompt_sent": False,
        }

    print("[EXTERNAL AI DESKTOP WINDOW] ChatGPT")
    _focus_window(window)
    window, prompt_control, readiness = _wait_for_prompt(
        Desktop,
        window,
        timeout_seconds=18 if app_id else 8,
    )
    focused_companion = False
    if readiness == "NOT_FOUND":
        companion_window, companion_control, companion_status = _open_companion(
            Desktop, keyboard, window
        )
        if companion_status in {"READY", "FOCUSED_ONLY"}:
            window = companion_window
            prompt_control = companion_control
            readiness = companion_status
            focused_companion = companion_status == "FOCUSED_ONLY"
    if readiness == "LOGIN_REQUIRED":
        return {
            "status": "DESKTOP_LOGIN_REQUIRED",
            "reason": "Sign in to ChatGPT Desktop in the visible app.",
            "provider": "ChatGPT Desktop",
            "outbound_prompt": prompt,
            "prompt_sent": False,
        }
    if readiness not in {"READY", "FOCUSED_ONLY"}:
        return {
            "status": "DESKTOP_INPUT_NOT_FOUND",
            "reason": (
                "Neither the main ChatGPT Desktop window nor its official Companion "
                "Window exposed a safe message input."
            ),
            "provider": "ChatGPT Desktop",
            "outbound_prompt": prompt,
            "prompt_sent": False,
        }

    before_texts = _accessible_texts(window)
    before_copy_count = len(_buttons_named(window, COPY_LABELS))
    if focused_companion:
        send_status = (
            "FOCUSED_SENT"
            if _enter_focused_companion(keyboard, prompt)
            else "INPUT_FAILED"
        )
    else:
        send_status = _enter_prompt(prompt_control, keyboard, prompt)
    if send_status not in {"SENT", "FOCUSED_SENT"}:
        return {
            "status": (
                "DESKTOP_SEND_UNCERTAIN"
                if send_status == "SEND_UNCERTAIN"
                else "DESKTOP_SEND_FAILED"
            ),
            "reason": (
                "The prompt was entered, but Bekki could not confirm whether it was sent."
                if send_status == "SEND_UNCERTAIN"
                else "The ChatGPT Desktop input was found, but the prompt was not entered."
            ),
            "provider": "ChatGPT Desktop",
            "outbound_prompt": prompt,
            "prompt_sent": None if send_status == "SEND_UNCERTAIN" else False,
        }
    print(
        "[EXTERNAL AI DESKTOP PROMPT SENT]",
        "source=" + str(source_kind),
        "route=" + ("companion_focus" if focused_companion else "uia_input"),
    )
    minimized = _background_after_send(window, previous_foreground)
    try:
        answer = _wait_for_answer(
            window,
            prompt,
            before_texts,
            before_copy_count,
            timeout_seconds,
            include_hidden=minimized,
        )
    finally:
        _minimize_after_read(window, minimized)
    if not answer:
        return {
            "status": (
                "DESKTOP_SEND_UNCERTAIN"
                if focused_companion
                else "DESKTOP_RESPONSE_TIMEOUT"
            ),
            "reason": (
                "Bekki used the focused Companion Window but could not confirm a sent prompt or readable answer."
                if focused_companion
                else "The prompt was sent, but no completed desktop answer became readable."
            ),
            "provider": "ChatGPT Desktop",
            "outbound_prompt": prompt,
            "prompt_sent": None if focused_companion else True,
        }
    print("[EXTERNAL AI DESKTOP ANSWER RECEIVED]", "chars=" + str(len(answer)))
    return {
        "status": "COMPLETED",
        "provider": "ChatGPT Desktop",
        "source_kind": str(source_kind),
        "outbound_prompt": prompt,
        "answer": answer,
        "verification_status": "UNVERIFIED_EXTERNAL_AI",
        "prompt_sent": True,
    }
