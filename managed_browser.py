"""One persistent normal Edge session shared by every Bekki web reader."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import requests


CDP_PORT = 9225
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
PROFILE_NAME = "unified_browser_profile"
_browser_process = None
_announced_ready = False
_legacy_cleanup_done = False
_background_announced = False


def app_data_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        path = base / "Bekki"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Bekki"
    else:
        path = Path.home() / ".local" / "share" / "Bekki"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir():
    path = app_data_dir() / PROFILE_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def edge_executable():
    candidates = []
    if sys.platform == "win32":
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(
                    Path(root)
                    / "Microsoft"
                    / "Edge"
                    / "Application"
                    / "msedge.exe"
                )
    elif sys.platform == "darwin":
        candidates.append(
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
        )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Microsoft Edge was not found for Bekki Browser.")


def cdp_is_ready():
    try:
        with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def browser_mode():
    """Read the shared browser's public CDP headless marker."""

    try:
        response = requests.get(CDP_URL + "/json/version", timeout=1.0)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return "unknown"
    user_agent = str(payload.get("User-Agent") or "")
    if "HeadlessChrome/" in user_agent:
        return "headless"
    return "headed" if user_agent else "unknown"


def _announce_ready(attached):
    global _announced_ready
    if _announced_ready:
        return
    print(
        "[BEKKI BROWSER]",
        "mode=background",
        "port=" + str(CDP_PORT),
        "session=" + ("attached" if attached else "started"),
    )
    _announced_ready = True


def close_legacy_managed_browsers():
    """Best-effort one-time cleanup of only Bekki's retired Edge sessions."""

    global _legacy_cleanup_done
    if _legacy_cleanup_done:
        return
    _legacy_cleanup_done = True
    if sys.platform != "win32":
        return
    script = r"""
$legacy = Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" |
    Where-Object {
        $line = [string]$_.CommandLine
        ($line -like '*--remote-debugging-port=9223*' -or
         $line -like '*--remote-debugging-port=9224*') -and
        ($line -like '*social_browser_profile*' -or
         $line -like '*casper_browser_profile*')
    }
foreach ($process in $legacy) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output $process.ProcessId
}
"""
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
            check=False,
        )
        cleaned = [
            line.strip()
            for line in str(completed.stdout or "").splitlines()
            if line.strip().isdigit()
        ]
        if cleaned:
            print("[BEKKI BROWSER LEGACY CLEANUP]", "processes=" + str(len(cleaned)))
    except Exception as error:
        print("[BEKKI BROWSER LEGACY CLEANUP ERROR]", repr(error))


def ensure_browser():
    """Start or attach to Bekki's single minimized persistent Edge process."""

    global _browser_process
    close_legacy_managed_browsers()
    if cdp_is_ready():
        if browser_mode() == "headless":
            raise RuntimeError(
                "Bekki's unified browser port is occupied by a headless process."
            )
        _announce_ready(attached=True)
        return

    command = [
        edge_executable(),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile_dir()}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-minimized",
        "--window-size=1280,900",
        "--disable-translate",
        "--disable-features=msEdgeTranslate,TranslateUI",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "about:blank",
    ]
    _browser_process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 12
    while time.time() < deadline:
        if cdp_is_ready():
            if browser_mode() == "headless":
                raise RuntimeError(
                    "Bekki Browser unexpectedly started in headless mode."
                )
            _announce_ready(attached=False)
            return
        time.sleep(0.25)
    raise RuntimeError("Bekki Browser did not start.")


def keep_page_background(context, page):
    """Best-effort minimize the Edge window without changing page rendering."""

    global _background_announced
    if not hasattr(context, "new_cdp_session"):
        return False
    session = None
    try:
        session = context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget", {})
        window_id = int(window.get("windowId"))
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {"windowState": "minimized"},
            },
        )
        if not _background_announced:
            print(
                "[BEKKI BROWSER BACKGROUND]",
                "window=minimized",
                "profile=" + PROFILE_NAME,
            )
            _background_announced = True
        return True
    except Exception as error:
        print("[BEKKI BROWSER BACKGROUND ERROR]", repr(error))
        return False
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def open_human_handoff(url):
    """Show one URL in the same persistent profile for user verification."""

    from urllib.parse import urlparse

    target = str(url or "").strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Human handoff requires a public web URL.")
    ensure_browser()
    subprocess.Popen(
        [
            edge_executable(),
            f"--user-data-dir={profile_dir()}",
            "--profile-directory=Default",
            "--new-window",
            "--start-maximized",
            target,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("[BEKKI BROWSER HANDOFF]", parsed.netloc)
    return True
