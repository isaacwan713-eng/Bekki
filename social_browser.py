"""Persistent local browser session for user-authorized social research."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import requests

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)


CDP_PORT = 9223
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

SOCIAL_DOMAINS = {
    "xiaohongshu": ("xiaohongshu.com", "rednote.com"),
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
}


def app_data_dir():
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home()))
        )
        path = base / "Bekki"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Bekki"
    else:
        path = Path.home() / ".local" / "share" / "Bekki"

    path.mkdir(parents=True, exist_ok=True)
    return path


def browser_profile_dir():
    path = app_data_dir() / "social_browser_profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def edge_executable():
    candidates = []

    if sys.platform == "win32":
        for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env_name)
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

    raise RuntimeError(
        "Microsoft Edge was not found. Install Edge before using social research."
    )


def cdp_is_ready():
    try:
        with socket.create_connection(
            ("127.0.0.1", CDP_PORT),
            timeout=0.5,
        ):
            return True
    except OSError:
        return False


def ensure_social_browser():
    """Start Bekki's separate local Edge profile if it is not running."""

    if cdp_is_ready():
        return

    command = [
        edge_executable(),
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={browser_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--headless=new",
        "--window-size=800,600",
    ]

    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 12
    while time.time() < deadline:
        if cdp_is_ready():
            return
        time.sleep(0.25)

    raise RuntimeError("Bekki social browser did not start.")


def social_search_url(platform, query):
    if platform == "xiaohongshu":
        return (
            "https://www.rednote.com/search_result?keyword="
            + quote(query)
            + "&type=51"
        )

    if platform == "instagram":
        return "https://www.instagram.com/"

    if platform == "x":
        return (
            "https://x.com/search?q="
            + quote(query)
            + "&src=typed_query&f=live"
        )

    raise ValueError("Unsupported social platform: " + str(platform))


def open_social_search(platform, query):
    """Open a social search in Bekki's managed Edge session."""

    ensure_social_browser()
    target_url = social_search_url(platform, query)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            CDP_URL
        )

        if not browser.contexts:
            raise RuntimeError(
                "Bekki social browser has no usable context."
            )

        context = browser.contexts[0]
        page = context.new_page()

        try:
            page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=8000,
            )
        except PlaywrightTimeoutError:
            # Social sites are often SPA pages. Keep the tab open and
            # let it continue loading instead of treating this as failure.
            print(
                "[SOCIAL NAVIGATION CONTINUES]",
                target_url,
            )

        return {
            "platform": platform,
            "url": page.url or target_url,
            "title": page.title(),
        }

def matches_expected_social_search(
    page_url,
    expected_url,
):
    """Return True only when the tab matches this exact search."""

    if not expected_url:
        return True

    expected = urlparse(expected_url)
    actual = urlparse(page_url)

    if expected.netloc != actual.netloc:
        return False

    if expected.path != actual.path:
        return False

    expected_query = parse_qs(expected.query).get(
        "q",
        [""],
    )[0].strip()

    actual_query = parse_qs(actual.query).get(
        "q",
        [""],
    )[0].strip()

    return not expected_query or actual_query == expected_query

def inspect_active_social_page(
    platform,
    expected_url=None,
):
    """Read visible text from the current user-authorized social page."""

    domains = SOCIAL_DOMAINS.get(platform, ())

    if not domains:
        raise ValueError(
            "Unsupported social platform: " + str(platform)
        )

    if not cdp_is_ready():
        raise RuntimeError(
            "Bekki social browser is not running."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            CDP_URL
        )

        matching_pages = []

        for context in browser.contexts:
            for page in context.pages:
                if (
                    any(domain in page.url for domain in domains) 
                and matches_expected_social_search(
                     page.url,
                     expected_url,)
                ):
                    matching_pages.append(page)

        if not matching_pages:
            raise RuntimeError(
                "No open " + platform
                + " page was found in Bekki social browser."
            )

        page = matching_pages[-1]
        page.bring_to_front()

        snapshots = []
        for index in range(4):
            snapshot = page.locator("body").inner_text(timeout=15000)
            snapshots.append(snapshot)

            if index < 3:
                page.evaluate(
                    """
                    () => window.scrollBy(
                    0,
                    Math.floor(window.innerHeight * 0.85)
                )
                """
            )
            page.wait_for_timeout(1000)
        seen_lines = set()
        unique_lines = []

        for snapshot in snapshots:
            for line in snapshot.splitlines():
                clean_line = line.strip()

                if clean_line and clean_line not in seen_lines:
                    seen_lines.add(clean_line)
                    unique_lines.append(clean_line)
        visible_text = "\n".join(unique_lines)


        return {
            "platform": platform,
            "url": page.url,
            "title": page.title(),
            "visible_text": visible_text[:18000],
        }

def close_social_browser():
    """Close tabs in Bekki's dedicated social browser only."""

    if not cdp_is_ready():
        return

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                CDP_URL
            )

            for context in browser.contexts:
                for page in list(context.pages):
                    try:
                        page.close(run_before_unload=False)
                    except Exception as error:
                        print(
                            "[SOCIAL TAB CLOSE ERROR]",
                            repr(error),
                        )

        print("[SOCIAL BROWSER TABS CLOSED]")

    except Exception as error:
        print(
            "[SOCIAL BROWSER CLOSE ERROR]",
            repr(error),
        )