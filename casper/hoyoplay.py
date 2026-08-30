"""Bounded HoYoPlay launch automation with UIA and visual fallback."""

import base64
import ctypes
from ctypes import wintypes
from io import BytesIO
import json
import os
import subprocess
import time


_UI_VISION_MODEL = (
    os.getenv("HOYOPLAY_VISION_MODEL", "gemma4:e4b").strip() or "gemma4:e4b"
)


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _RgbQuad(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", _BitmapInfoHeader),
        ("bmiColors", _RgbQuad * 1),
    ]


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("value", _InputUnion),
    ]


_POWERSHELL_SCRIPT = r'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Emit-Result([string]$status, [string]$window, [string]$control) {
    [ordered]@{
        status = $status
        window = $window
        control = $control
    } | ConvertTo-Json -Compress
    exit 0
}

$running = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match '^(GenshinImpact|YuanShen)$'
} | Select-Object -First 1
if ($null -ne $running) {
    Emit-Result "game_opened" $running.ProcessName "already_running"
}

$deadline = [DateTime]::UtcNow.AddSeconds(__TIMEOUT__)
$launcher = $null
while ([DateTime]::UtcNow -lt $deadline -and $null -eq $launcher) {
    $launcher = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowHandle -ne 0 -and (
            $_.ProcessName -match 'HoYoPlay' -or
            $_.MainWindowTitle -match 'HoYoPlay'
        )
    } | Select-Object -First 1
    if ($null -eq $launcher) { Start-Sleep -Milliseconds 400 }
}
if ($null -eq $launcher) {
    Emit-Result "launcher_not_ready" "HoYoPlay" ""
}

$root = [System.Windows.Automation.AutomationElement]::FromHandle(
    [IntPtr]$launcher.MainWindowHandle
)
if ($null -eq $root) {
    Emit-Result "launcher_not_ready" $launcher.MainWindowTitle ""
}

function Get-Nodes($automationRoot) {
    return $automationRoot.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
}

$nodes = Get-Nodes $root
$genshinNode = $null
foreach ($node in $nodes) {
    $name = [string]$node.Current.Name
    if ($name -match '(?i)Genshin\s*Impact' -or $name -match '原神') {
        $genshinNode = $node
        break
    }
}
if ($null -eq $genshinNode) {
    Emit-Result "game_identity_not_visible" $launcher.MainWindowTitle ""
}

# Select Genshin when the visible identity exposes a safe UIA action. If it is
# already the active page, its text is still enough to continue to the exact
# launch-button search below.
try {
    $selection = $genshinNode.GetCurrentPattern(
        [System.Windows.Automation.SelectionItemPattern]::Pattern
    )
    $selection.Select()
    Start-Sleep -Milliseconds 600
} catch {
    try {
        $gameInvoke = $genshinNode.GetCurrentPattern(
            [System.Windows.Automation.InvokePattern]::Pattern
        )
        $gameInvoke.Invoke()
        Start-Sleep -Milliseconds 600
    } catch { }
}

$nodes = Get-Nodes $root
$button = $null
$launchNames = @(
    'Start Game', 'Launch Game', 'Play Game', 'Launch', 'Play',
    '开始游戏', '启动游戏', '开始', '启动'
)
foreach ($wanted in $launchNames) {
    foreach ($node in $nodes) {
        $name = [string]$node.Current.Name
        if (
            $node.Current.ControlType -eq
                [System.Windows.Automation.ControlType]::Button -and
            $node.Current.IsEnabled -and
            $name -eq $wanted
        ) {
            $button = $node
            break
        }
    }
    if ($null -ne $button) { break }
}
if ($null -eq $button) {
    Emit-Result "launch_control_not_found" $launcher.MainWindowTitle ""
}

$controlName = [string]$button.Current.Name
try {
    $invoke = $button.GetCurrentPattern(
        [System.Windows.Automation.InvokePattern]::Pattern
    )
    $invoke.Invoke()
} catch {
    Emit-Result "launch_control_unavailable" $launcher.MainWindowTitle $controlName
}

$verifyDeadline = [DateTime]::UtcNow.AddSeconds(25)
while ([DateTime]::UtcNow -lt $verifyDeadline) {
    $game = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '^(GenshinImpact|YuanShen)$'
    } | Select-Object -First 1
    if ($null -ne $game) {
        Emit-Result "game_opened" $launcher.MainWindowTitle $controlName
    }
    Start-Sleep -Milliseconds 500
}
Emit-Result "launch_dispatched" $launcher.MainWindowTitle $controlName
'''

_WINDOW_RECT_SCRIPT = r'''
$ErrorActionPreference = "Stop"
Add-Type @"
using System;
using System.Runtime.InteropServices;
public struct BekkiRect {
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}
public static class BekkiWindowApi {
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out BekkiRect rect);
}
"@
[void][BekkiWindowApi]::SetProcessDPIAware()
$launcher = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowHandle -ne 0 -and (
        $_.ProcessName -match 'HoYoPlay' -or
        $_.MainWindowTitle -match 'HoYoPlay'
    )
} | Select-Object -First 1
if ($null -eq $launcher) {
    @{status="launcher_not_ready"} | ConvertTo-Json -Compress
    exit 0
}
[void][BekkiWindowApi]::ShowWindowAsync($launcher.MainWindowHandle, 9)
[void][BekkiWindowApi]::SetForegroundWindow($launcher.MainWindowHandle)
Start-Sleep -Milliseconds 800
$rect = New-Object BekkiRect
if (-not [BekkiWindowApi]::GetWindowRect($launcher.MainWindowHandle, [ref]$rect)) {
    @{status="window_rect_unavailable"} | ConvertTo-Json -Compress
    exit 0
}
[ordered]@{
    status="ready"
    hwnd=[Int64]$launcher.MainWindowHandle
    title=[string]$launcher.MainWindowTitle
    left=$rect.Left
    top=$rect.Top
    right=$rect.Right
    bottom=$rect.Bottom
} | ConvertTo-Json -Compress
'''

_VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "game_identity": {
            "type": "string",
            "enum": ["GENSHIN", "NOT_VISIBLE"],
        },
        "button_visible": {"type": "boolean"},
        "button_text": {
            "type": "string",
            "enum": [
                "Start Game",
                "Launch Game",
                "Play Game",
                "Launch",
                "Play",
                "开始游戏",
                "启动游戏",
                "开始",
                "启动",
                "NONE",
            ],
        },
        "center_x_1000": {"type": "integer", "minimum": 0, "maximum": 1000},
        "center_y_1000": {"type": "integer", "minimum": 0, "maximum": 1000},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "reason": {"type": "string"},
    },
    "required": [
        "game_identity",
        "button_visible",
        "button_text",
        "center_x_1000",
        "center_y_1000",
        "confidence",
        "reason",
    ],
    "additionalProperties": False,
}

_VISION_PROMPT = """You inspect one screenshot of the foreground HoYoPlay
launcher. This is a visual classification and pointing task, not a request for
instructions or code.

Confirm that the visible launcher page is specifically Genshin Impact/原神 and
locate the center of its exact enabled game-launch button. Return coordinates
normalized from 0 to 1000 across the screenshot width and height.

Return one JSON object only according to the supplied schema.
- game_identity is GENSHIN only when the screenshot visibly identifies Genshin
  Impact or 原神. A HoYoPlay logo alone is not enough.
- button_visible is true only for a visible Start Game/Launch/Play equivalent
  belonging to that Genshin page.
- button_text must use one exact allowed schema value.
- Use confidence high only when both the game identity and button are clear.
- Never guess a coordinate. If uncertain, use NOT_VISIBLE, false, NONE, low,
  and coordinates 0,0.
"""

_TARGET_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "target_correct": {"type": "boolean"},
        "corrected_x_1000": {"type": "integer", "minimum": 0, "maximum": 1000},
        "corrected_y_1000": {"type": "integer", "minimum": 0, "maximum": 1000},
        "confidence": {"type": "string", "enum": ["high", "low"]},
        "reason": {"type": "string"},
    },
    "required": [
        "target_correct",
        "corrected_x_1000",
        "corrected_y_1000",
        "confidence",
        "reason",
    ],
    "additionalProperties": False,
}

_TARGET_AUDIT_PROMPT = """Inspect the annotated HoYoPlay screenshot. A red
circle and crosshair mark the proposed click location for the visible Genshin
Impact/原神 launch button.

Return JSON only. target_correct is true only when the exact center of the red
crosshair is visibly inside the enabled Start Game/开始游戏 button. Seeing the
button somewhere else is not enough. If the marker is wrong, return the actual
button center as coordinates normalized 0..1000 across the whole screenshot.
When target_correct is true, corrected_x_1000 and corrected_y_1000 must repeat
the marked location rather than introducing a different point.
Use high confidence only when the marker or corrected center is visually clear.
Never approve a marker over a banner, background art, navigation item, or text
that is not the game-launch button.
"""

_ALLOWED_LAUNCH_LABELS = {
    "Start Game",
    "Launch Game",
    "Play Game",
    "Launch",
    "Play",
    "开始游戏",
    "启动游戏",
    "开始",
    "启动",
}


def _last_json_line(output):
    for line in reversed(str(output or "").splitlines()):
        try:
            value = json.loads(line.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _foreground_window_rect():
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _WINDOW_RECT_SCRIPT,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = _last_json_line(completed.stdout)
    if not isinstance(value, dict) or value.get("status") != "ready":
        return None
    try:
        left = int(value["left"])
        top = int(value["top"])
        right = int(value["right"])
        bottom = int(value["bottom"])
        hwnd = int(value["hwnd"])
    except (KeyError, TypeError, ValueError):
        return None
    width = right - left
    height = bottom - top
    if hwnd <= 0 or width < 300 or height < 200 or width > 8000 or height > 5000:
        return None
    return {
        "hwnd": hwnd,
        "title": str(value.get("title") or "HoYoPlay"),
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": width,
        "height": height,
    }


def _capture_window_png_native(rect):
    """Capture one HWND through GDI when desktop ImageGrab is unavailable."""
    if os.name != "nt":
        return b""
    width = int(rect.get("width") or 0)
    height = int(rect.get("height") or 0)
    hwnd = int(rect.get("hwnd") or 0)
    if hwnd <= 0 or width <= 0 or height <= 0:
        return b""
    window_dc = memory_dc = bitmap = old_object = None
    try:
        from PIL import Image

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        user32.GetWindowDC.argtypes = [wintypes.HWND]
        user32.GetWindowDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        user32.PrintWindow.restype = wintypes.BOOL
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(_BitmapInfo),
            wintypes.UINT,
        ]
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.argtypes = [wintypes.HDC]

        window_handle = wintypes.HWND(hwnd)
        window_dc = user32.GetWindowDC(window_handle)
        if not window_dc:
            return b""
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        if not memory_dc or not bitmap:
            return b""
        old_object = gdi32.SelectObject(memory_dc, bitmap)
        captured = user32.PrintWindow(window_handle, memory_dc, 2)
        if not captured:
            captured = user32.PrintWindow(window_handle, memory_dc, 0)
        if not captured:
            return b""

        info = _BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        pixels = ctypes.create_string_buffer(width * height * 4)
        rows = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            pixels,
            ctypes.byref(info),
            0,
        )
        if rows != height:
            return b""
        image = Image.frombuffer(
            "RGB",
            (width, height),
            bytes(pixels),
            "raw",
            "BGRX",
            0,
            -1,
        )
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
        print("[HOYOPLAY NATIVE CAPTURE ERROR]", repr(error))
        return b""
    finally:
        try:
            if old_object and memory_dc:
                ctypes.windll.gdi32.SelectObject(memory_dc, old_object)
            if bitmap:
                ctypes.windll.gdi32.DeleteObject(bitmap)
            if memory_dc:
                ctypes.windll.gdi32.DeleteDC(memory_dc)
            if window_dc:
                ctypes.windll.user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)
        except (AttributeError, OSError, TypeError, ValueError):
            pass


def _capture_window_png(rect):
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(
            bbox=(rect["left"], rect["top"], rect["right"], rect["bottom"]),
            all_screens=True,
        )
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except (ImportError, OSError, ValueError) as error:
        print("[HOYOPLAY IMAGEGRAB ERROR]", repr(error))
        png_bytes = _capture_window_png_native(rect)
        if png_bytes:
            print("[HOYOPLAY CAPTURE FALLBACK] win32_printwindow")
        return png_bytes


def _parse_model_json(raw):
    candidate = str(raw or "").strip()
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline >= 0:
            candidate = candidate[first_newline + 1:]
        if candidate.rstrip().endswith("```"):
            candidate = candidate.rstrip()[:-3].rstrip()
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _annotate_visual_target(png_bytes, plan):
    try:
        from PIL import Image, ImageDraw

        normalized_x = int(plan.get("center_x_1000"))
        normalized_y = int(plan.get("center_y_1000"))
        if not (1 <= normalized_x <= 999 and 1 <= normalized_y <= 999):
            return b""
        image = Image.open(BytesIO(png_bytes)).convert("RGB")
        x = round(image.width * normalized_x / 1000)
        y = round(image.height * normalized_y / 1000)
        radius = max(18, round(min(image.width, image.height) * 0.025))
        draw = ImageDraw.Draw(image)
        # White outline keeps the red marker visible on both dark and red UI.
        draw.ellipse(
            (x - radius - 3, y - radius - 3, x + radius + 3, y + radius + 3),
            outline="white",
            width=7,
        )
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            outline="red",
            width=6,
        )
        draw.line((x - radius * 2, y, x + radius * 2, y), fill="red", width=6)
        draw.line((x, y - radius * 2, x, y + radius * 2), fill="red", width=6)
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except (ImportError, OSError, TypeError, ValueError):
        return b""


def _audit_visual_target(png_bytes, plan, tools):
    if not isinstance(plan, dict):
        return plan
    if (
        plan.get("game_identity") != "GENSHIN"
        or plan.get("button_visible") is not True
        or plan.get("button_text") not in _ALLOWED_LAUNCH_LABELS
        or str(plan.get("confidence") or "").lower() != "high"
    ):
        return plan
    current = dict(plan)
    for audit_round in (1, 2):
        annotated = _annotate_visual_target(png_bytes, current)
        if not annotated:
            return {
                "_runtime_status": "vision_output_invalid",
                "reason": "Could not annotate the proposed click target.",
            }
        try:
            raw = tools.call_model(
                _TARGET_AUDIT_PROMPT,
                num_ctx=2048,
                num_predict=240,
                think=False,
                model_name=_UI_VISION_MODEL,
                response_format=_TARGET_AUDIT_SCHEMA,
                images=[base64.b64encode(annotated).decode("ascii")],
            )
        except Exception as error:
            print("[HOYOPLAY TARGET AUDIT ERROR]", repr(error))
            return {
                "_runtime_status": "vision_model_unavailable",
                "reason": type(error).__name__,
            }
        audit = _parse_model_json(raw)
        if not isinstance(audit, dict):
            return {
                "_runtime_status": "vision_output_invalid",
                "reason": "The target audit returned invalid JSON.",
            }
        audit_confidence = str(audit.get("confidence") or "").lower()
        if audit_confidence != "high":
            current["confidence"] = "low"
            current["reason"] = str(audit.get("reason") or "Target audit uncertain")
            return current
        try:
            proposed_x = int(current.get("center_x_1000"))
            proposed_y = int(current.get("center_y_1000"))
            corrected_x = int(audit.get("corrected_x_1000"))
            corrected_y = int(audit.get("corrected_y_1000"))
        except (TypeError, ValueError):
            current["confidence"] = "low"
            return current
        if not (1 <= corrected_x <= 999 and 1 <= corrected_y <= 999):
            current["confidence"] = "low"
            return current
        marker_matches_returned_point = (
            abs(corrected_x - proposed_x) <= 25
            and abs(corrected_y - proposed_y) <= 25
        )
        if audit.get("target_correct") is True and marker_matches_returned_point:
            print("[HOYOPLAY TARGET VERIFIED]", "round=" + str(audit_round))
            return current
        if audit.get("target_correct") is True:
            print(
                "[HOYOPLAY TARGET AUDIT CONFLICT]",
                "proposed=" + str(proposed_x) + "," + str(proposed_y),
                "returned=" + str(corrected_x) + "," + str(corrected_y),
            )
        current["center_x_1000"] = corrected_x
        current["center_y_1000"] = corrected_y
        print(
            "[HOYOPLAY TARGET CORRECTED]",
            str(corrected_x) + "," + str(corrected_y),
            "round=" + str(audit_round),
        )
    current["confidence"] = "low"
    current["reason"] = "Corrected target was not independently verified."
    return current


def _visual_launch_plan(png_bytes):
    if not png_bytes:
        return None
    try:
        import tools

        try:
            tools.unload_model("llama3.2:latest")
            tools.wait_for_model_unloaded(
                "llama3.2:latest",
                timeout_seconds=10,
            )
        except Exception as unload_error:
            print("[HOYOPLAY VISION UNLOAD SKIPPED]", repr(unload_error))
        encoded_image = base64.b64encode(png_bytes).decode("ascii")
        last_error = None
        for attempt in (1, 2):
            try:
                raw = tools.call_model(
                    _VISION_PROMPT,
                    num_ctx=2048,
                    num_predict=320,
                    think=False,
                    model_name=_UI_VISION_MODEL,
                    response_format=_VISION_SCHEMA,
                    images=[encoded_image],
                )
                parsed = _parse_model_json(raw)
                if parsed is None:
                    return {
                        "_runtime_status": "vision_output_invalid",
                        "reason": "The vision model returned invalid JSON.",
                    }
                return _audit_visual_target(png_bytes, parsed, tools)
            except Exception as error:
                last_error = error
                print(
                    "[HOYOPLAY VISION ERROR]",
                    "attempt=" + str(attempt),
                    "model=" + _UI_VISION_MODEL,
                    repr(error),
                )
                if attempt == 1:
                    try:
                        tools.unload_model(_UI_VISION_MODEL)
                        tools.wait_for_model_unloaded(
                            _UI_VISION_MODEL,
                            timeout_seconds=10,
                        )
                    except Exception as unload_error:
                        print(
                            "[HOYOPLAY VISION RETRY CLEANUP SKIPPED]",
                            repr(unload_error),
                        )
                    print("[HOYOPLAY VISION RETRY]", _UI_VISION_MODEL)
        return {
            "_runtime_status": "vision_model_unavailable",
            "reason": type(last_error).__name__ if last_error else "unknown",
        }
    except Exception as error:
        print("[HOYOPLAY VISION ERROR]", repr(error))
        return {
            "_runtime_status": "vision_model_unavailable",
            "reason": type(error).__name__,
        }


def _validated_click_point(plan, rect):
    if not isinstance(plan, dict):
        return None
    if plan.get("game_identity") != "GENSHIN":
        return None
    if plan.get("button_visible") is not True:
        return None
    if plan.get("button_text") not in _ALLOWED_LAUNCH_LABELS:
        return None
    if str(plan.get("confidence") or "").lower() != "high":
        return None
    try:
        normalized_x = int(plan.get("center_x_1000"))
        normalized_y = int(plan.get("center_y_1000"))
    except (TypeError, ValueError):
        return None
    if not (1 <= normalized_x <= 999 and 1 <= normalized_y <= 999):
        return None
    x = rect["left"] + round(rect["width"] * normalized_x / 1000)
    y = rect["top"] + round(rect["height"] * normalized_y / 1000)
    if not (rect["left"] < x < rect["right"]):
        return None
    if not (rect["top"] < y < rect["bottom"]):
        return None
    return x, y


def _send_absolute_mouse_click(user32, point):
    """Send one bounded absolute click when SetCursorPos is unavailable."""
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(_Input),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT
    virtual_left = int(user32.GetSystemMetrics(76))
    virtual_top = int(user32.GetSystemMetrics(77))
    virtual_width = int(user32.GetSystemMetrics(78))
    virtual_height = int(user32.GetSystemMetrics(79))
    if virtual_width <= 1 or virtual_height <= 1:
        print("[HOYOPLAY CLICK ERROR]", "stage=virtual_screen")
        return False
    x = int(point[0])
    y = int(point[1])
    if not (
        virtual_left <= x < virtual_left + virtual_width
        and virtual_top <= y < virtual_top + virtual_height
    ):
        print("[HOYOPLAY CLICK ERROR]", "stage=virtual_bounds")
        return False
    absolute_x = round((x - virtual_left) * 65535 / (virtual_width - 1))
    absolute_y = round((y - virtual_top) * 65535 / (virtual_height - 1))
    events = (_Input * 3)()
    events[0].type = 0
    events[0].mi = _MouseInput(
        absolute_x,
        absolute_y,
        0,
        0x0001 | 0x4000 | 0x8000,
        0,
        0,
    )
    events[1].type = 0
    events[1].mi = _MouseInput(0, 0, 0, 0x0002, 0, 0)
    events[2].type = 0
    events[2].mi = _MouseInput(0, 0, 0, 0x0004, 0, 0)
    for stage, event, pause_after in (
        ("send_input_move", events[0], 0.15),
        ("send_input_down", events[1], 0.10),
        ("send_input_up", events[2], 0.0),
    ):
        sent = int(
            user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_Input))
        )
        if sent != 1:
            try:
                error_code = int(ctypes.get_last_error())
            except (AttributeError, TypeError, ValueError):
                error_code = 0
            print(
                "[HOYOPLAY CLICK ERROR]",
                "stage=" + stage,
                "sent=" + str(sent),
                "winerror=" + str(error_code),
            )
            return False
        if pause_after:
            time.sleep(pause_after)
    return True


def _click_foreground_window(hwnd, point):
    if os.name != "nt" or not point:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindowAsync.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = wintypes.BOOL
        user32.mouse_event.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        ]
        user32.mouse_event.restype = None

        window_handle = wintypes.HWND(int(hwnd))
        user32.ShowWindowAsync(window_handle, 9)
        user32.BringWindowToTop(window_handle)
        user32.SetForegroundWindow(window_handle)
        time.sleep(0.5)
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground != int(hwnd):
            print(
                "[HOYOPLAY CLICK ERROR]",
                "stage=foreground",
                "expected=" + str(int(hwnd)),
                "actual=" + str(foreground),
            )
            return False
        if not user32.SetCursorPos(int(point[0]), int(point[1])):
            print(
                "[HOYOPLAY CLICK FALLBACK]",
                "set_cursor_to_send_input",
            )
            if not _send_absolute_mouse_click(user32, point):
                return False
            print(
                "[HOYOPLAY CLICK DISPATCHED]",
                str(point[0]) + "," + str(point[1]),
                "route=send_input",
            )
            return True
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        print(
            "[HOYOPLAY CLICK DISPATCHED]",
            str(point[0]) + "," + str(point[1]),
            "route=set_cursor",
        )
        return True
    except (AttributeError, OSError, TypeError, ValueError) as error:
        print("[HOYOPLAY CLICK ERROR]", "stage=win32", repr(error))
        return False


def _wait_for_genshin_process(timeout_seconds=25):
    deadline = time.monotonic() + max(1, min(int(timeout_seconds), 30))
    while time.monotonic() < deadline:
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "@(Get-Process -ErrorAction SilentlyContinue | "
                    "Where-Object {$_.ProcessName -match "
                    "'^(GenshinImpact|YuanShen)$'}).Count",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if int(str(completed.stdout or "0").strip() or "0") > 0:
                return True
        except (OSError, subprocess.SubprocessError, TypeError, ValueError):
            pass
        time.sleep(0.5)
    return False


def _launch_genshin_via_vision():
    rect = _foreground_window_rect()
    if not rect:
        return {"status": "vision_window_unavailable"}
    png_bytes = _capture_window_png(rect)
    if not png_bytes:
        return {"status": "vision_capture_failed", "window": rect["title"]}
    plan = _visual_launch_plan(png_bytes)
    runtime_status = str((plan or {}).get("_runtime_status") or "")
    if runtime_status:
        return {
            "status": runtime_status,
            "window": rect["title"],
            "reason": str((plan or {}).get("reason") or ""),
        }
    point = _validated_click_point(plan, rect)
    if not point:
        return {
            "status": "vision_target_unverified",
            "window": rect["title"],
            "reason": str((plan or {}).get("reason") or ""),
        }
    if not _click_foreground_window(rect["hwnd"], point):
        return {
            "status": "vision_click_failed",
            "window": rect["title"],
            "control": str(plan.get("button_text") or ""),
        }
    print(
        "[HOYOPLAY VISION CLICK]",
        str(plan.get("button_text") or ""),
        "at",
        str(point[0]) + "," + str(point[1]),
    )
    return {
        "status": (
            "game_opened" if _wait_for_genshin_process() else "launch_dispatched"
        ),
        "window": rect["title"],
        "control": str(plan.get("button_text") or ""),
        "route": "vision_verified_click",
    }


def launch_genshin_via_ui(timeout_seconds=25):
    """Click only a Genshin-confirmed HoYoPlay launch control via UIA."""
    if os.name != "nt":
        return {"status": "unsupported_platform"}
    bounded_timeout = max(10, min(int(timeout_seconds), 45))
    script = _POWERSHELL_SCRIPT.replace("__TIMEOUT__", str(bounded_timeout))
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=bounded_timeout + 35,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "automation_error", "reason": repr(error)}
    result = _last_json_line(completed.stdout)
    if isinstance(result, dict) and result.get("status"):
        if result.get("status") in {
            "game_identity_not_visible",
            "launch_control_not_found",
            "launch_control_unavailable",
        }:
            print("[HOYOPLAY UIA FALLBACK]", result.get("status"))
            return _launch_genshin_via_vision()
        return result
    return {
        "status": "automation_error",
        "reason": str(completed.stderr or "").strip()[:500],
    }
