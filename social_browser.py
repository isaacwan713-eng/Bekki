"""Persistent local browser session for user-authorized social research."""

import base64
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import requests

CDP_PORT = 9223
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

SOCIAL_DOMAINS = {
    "xiaohongshu": ("xiaohongshu.com", "rednote.com"),
    "instagram": ("instagram.com",),
    "x": ("x.com", "twitter.com"),
}
MAX_VISUAL_FRAMES = 3
MAX_POST_CANDIDATES = 30
MAX_POST_DETAILS = 7


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

    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )

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

    expected_parameters = parse_qs(expected.query)
    actual_parameters = parse_qs(actual.query)
    for key in ("q", "keyword"):
        expected_query = expected_parameters.get(key, [""])[0].strip()
        if not expected_query:
            continue
        actual_query = actual_parameters.get(key, [""])[0].strip()
        return actual_query == expected_query
    return True


def _allowed_social_url(platform, value):
    """Return a bounded public post URL from the selected platform only."""

    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or not hostname:
        return ""
    if not any(
        hostname == domain or hostname.endswith("." + domain)
        for domain in SOCIAL_DOMAINS.get(platform, ())
    ):
        return ""
    path = parsed.path.lower()
    if platform == "xiaohongshu" and not any(
        marker in path for marker in ("/explore/", "/discovery/item/")
    ):
        return ""
    if platform == "instagram" and not any(
        marker in path for marker in ("/p/", "/reel/")
    ):
        return ""
    if platform == "x" and "/status/" not in path:
        return ""
    return str(value).strip()[:2048]


def _extract_post_candidates(page, platform):
    """Collect visible post links and their real image URLs from the result grid."""

    try:
        raw_items = page.evaluate(
            r"""
            () => {
                const output = [];
                const seen = new Set();
                for (const anchor of document.querySelectorAll('a[href]')) {
                    const href = anchor.href || '';
                    if (!href || seen.has(href)) continue;
                    let container = anchor;
                    for (let depth = 0; depth < 6 && container.parentElement; depth++) {
                        const parent = container.parentElement;
                        const parentText = (parent.innerText || '').trim();
                        container = parent;
                        if (parentText.length >= 8 && parentText.length <= 1800) break;
                    }
                    const image = anchor.querySelector('img') || container.querySelector('img');
                    if (!image) continue;
                    const text = (container.innerText || anchor.innerText || '')
                        .replace(/\s+/g, ' ').trim();
                    if (!text) continue;
                    const imageUrl = image.currentSrc || image.src ||
                        image.getAttribute('data-src') || '';
                    output.push({
                        url: href,
                        visible_text: text.slice(0, 1400),
                        image_url: imageUrl,
                        image_alt: (image.alt || '').slice(0, 240),
                    });
                    seen.add(href);
                    if (output.length >= 60) break;
                }
                return output;
            }
            """
        )
    except Exception as error:
        print("[SOCIAL POST CANDIDATE ERROR]", repr(error))
        return []
    candidates = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        url = _allowed_social_url(platform, item.get("url"))
        visible_text = str(item.get("visible_text") or "").strip()[:1400]
        image_url = str(item.get("image_url") or "").strip()[:2048]
        if not url or not visible_text:
            continue
        if not image_url.lower().startswith("https://"):
            image_url = ""
        candidates.append(
            {
                "platform": platform,
                "url": url,
                "visible_text": visible_text,
                "image_url": image_url,
                "image_alt": str(item.get("image_alt") or "").strip()[:240],
            }
        )
        if len(candidates) >= MAX_POST_CANDIDATES:
            break
    return candidates


def _find_social_search_page(browser, platform, expected_url=None):
    domains = SOCIAL_DOMAINS.get(platform, ())
    matching_pages = []
    for context in browser.contexts:
        for page in context.pages:
            if (
                any(domain in page.url for domain in domains)
                and matches_expected_social_search(page.url, expected_url)
            ):
                matching_pages.append(page)
    return matching_pages[-1] if matching_pages else None


def _title_card_data(locator):
    """Read the smallest visible ancestor that joins a title, image and link."""

    try:
        raw = locator.evaluate(
            r"""
            (node) => {
                let current = node;
                let fallback = null;
                for (let depth = 0; current && depth < 10; depth++) {
                    const text = (current.innerText || current.textContent || '')
                        .replace(/\s+/g, ' ').trim();
                    const image = current.querySelector && current.querySelector('img');
                    const closestLink = current.closest && current.closest('a[href]');
                    const childLink = current.querySelector && current.querySelector('a[href]');
                    const link = closestLink || childLink;
                    if (text && !fallback) {
                        fallback = {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image ? (
                                image.currentSrc || image.src ||
                                image.getAttribute('data-src') || ''
                            ) : '',
                        };
                    }
                    if (text && image && text.length <= 2400) {
                        return {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image.currentSrc || image.src ||
                                image.getAttribute('data-src') || '',
                        };
                    }
                    current = current.parentElement;
                }
                return fallback || {visible_text: '', url: '', image_url: ''};
            }
            """
        )
    except Exception as error:
        print("[SOCIAL TITLE CARD ERROR]", repr(error))
        return {}
    return raw if isinstance(raw, dict) else {}


def resolve_social_post_targets(platform, post_titles, expected_url=None):
    """Locate recent posts across bounded result-grid scroll positions."""

    titles = [
        str(title or "").strip()[:300]
        for title in post_titles if str(title or "").strip()
    ][:7]
    if not titles or not cdp_is_ready():
        return []
    from playwright.sync_api import sync_playwright

    resolved = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        page = _find_social_search_page(browser, platform, expected_url)
        if page is None:
            return []
        page.bring_to_front()
        try:
            page.evaluate("() => window.scrollTo(0, 0)")
            page.wait_for_timeout(600)
        except Exception:
            pass
        unresolved = list(titles)
        for scan_index in range(8):
            for title in list(unresolved):
                try:
                    locator = page.get_by_text(title, exact=True)
                    if locator.count() < 1:
                        locator = page.get_by_text(title, exact=False)
                    if locator.count() < 1:
                        continue
                    locator = locator.first
                    card_data = _title_card_data(locator)
                    visible_text = str(
                        card_data.get("visible_text") or title
                    ).strip()[:1400]
                    image_url = str(
                        card_data.get("image_url") or ""
                    ).strip()[:2048]
                    if not image_url.lower().startswith("https://"):
                        image_url = ""
                    url = _allowed_social_url(platform, card_data.get("url"))
                    opened_by_click = False
                    if not url:
                        old_url = page.url
                        try:
                            old_scroll_y = page.evaluate("() => window.scrollY")
                        except Exception:
                            old_scroll_y = 0
                        old_pages = [
                            existing
                            for context in browser.contexts
                            for existing in context.pages
                        ]
                        locator.click(timeout=4000)
                        page.wait_for_timeout(1400)
                        new_pages = [
                            existing
                            for context in browser.contexts
                            for existing in context.pages
                            if existing not in old_pages
                        ]
                        opened_page = new_pages[-1] if new_pages else page
                        url = _allowed_social_url(platform, opened_page.url)
                        opened_by_click = bool(url)
                        if opened_page is not page:
                            try:
                                opened_page.close(run_before_unload=False)
                            except Exception:
                                pass
                        elif page.url != old_url:
                            try:
                                page.goto(
                                    expected_url or old_url,
                                    wait_until="domcontentloaded",
                                    timeout=8000,
                                )
                                page.wait_for_timeout(800)
                                page.evaluate(
                                    "(y) => window.scrollTo(0, y)",
                                    old_scroll_y,
                                )
                                page.wait_for_timeout(400)
                            except Exception as error:
                                print("[SOCIAL SEARCH RESTORE ERROR]", repr(error))
                    if not url:
                        continue
                    resolved.append(
                        {
                            "platform": platform,
                            "post_title": title,
                            "url": url,
                            "visible_text": visible_text,
                            "image_url": image_url,
                            "opened_by_click": opened_by_click,
                        }
                    )
                    unresolved.remove(title)
                except Exception as error:
                    print("[SOCIAL TITLE LOCATE ERROR]", repr(error))
            if not unresolved or scan_index >= 7:
                break
            try:
                movement = page.evaluate(
                    """
                    () => {
                        const before = window.scrollY;
                        window.scrollBy(0, Math.floor(window.innerHeight * 0.82));
                        return {before, after: window.scrollY};
                    }
                    """
                )
                page.wait_for_timeout(700)
                if (
                    isinstance(movement, dict)
                    and movement.get("after") == movement.get("before")
                ):
                    break
            except Exception:
                break
        if unresolved:
            print("[SOCIAL TITLE UNRESOLVED]", len(unresolved))
    return resolved

def inspect_active_social_page(
    platform,
    expected_url=None,
):
    """Read visible text from the current user-authorized social page."""

    from playwright.sync_api import sync_playwright

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

        page = _find_social_search_page(browser, platform, expected_url)

        if page is None:
            raise RuntimeError(
                "No open " + platform
                + " page was found in Bekki social browser."
            )
        page.bring_to_front()

        snapshots = []
        visual_frames = []
        post_candidates = []
        seen_candidate_urls = set()
        for index in range(4):
            snapshot = page.locator("body").inner_text(timeout=15000)
            snapshots.append(snapshot)
            for candidate in _extract_post_candidates(page, platform):
                url = str(candidate.get("url") or "").strip()
                if not url or url in seen_candidate_urls:
                    continue
                seen_candidate_urls.add(url)
                post_candidates.append(candidate)
                if len(post_candidates) >= MAX_POST_CANDIDATES:
                    break

            # Keep a small, bounded set of the actual visible result grid.
            # These frames are analyzed locally and never used as click or
            # navigation authority.
            if index < MAX_VISUAL_FRAMES:
                try:
                    image_bytes = page.screenshot(
                        type="jpeg",
                        quality=60,
                        full_page=False,
                        animations="disabled",
                    )
                    if image_bytes:
                        visual_frames.append(
                            base64.b64encode(image_bytes).decode("ascii")
                        )
                except Exception as error:
                    print(
                        "[SOCIAL SCREENSHOT ERROR]",
                        "frame=" + str(index + 1),
                        repr(error),
                    )

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
            "visual_frames": visual_frames[:MAX_VISUAL_FRAMES],
            "post_candidates": post_candidates,
        }


def inspect_social_post_details(targets):
    """Open up to seven grounded post links and read visible detail data."""

    safe_targets = []
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict):
            continue
        platform = str(target.get("platform") or "").strip()
        url = _allowed_social_url(platform, target.get("url"))
        if not url:
            continue
        safe_targets.append(
            {
                "platform": platform,
                "url": url,
                "post_title": str(target.get("post_title") or "").strip()[:300],
                "search_image_url": str(target.get("image_url") or "").strip()[:2048],
                "search_visible_text": str(
                    target.get("visible_text") or ""
                ).strip()[:1400],
            }
        )
        if len(safe_targets) >= MAX_POST_DETAILS:
            break
    if not safe_targets:
        return []
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

    details = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            return []
        context = browser.contexts[0]
        for target in safe_targets:
            page = context.new_page()
            try:
                try:
                    page.goto(
                        target["url"],
                        wait_until="domcontentloaded",
                        timeout=8000,
                    )
                except PlaywrightTimeoutError:
                    print("[SOCIAL POST NAVIGATION CONTINUES]", target["url"])
                page.wait_for_timeout(1600)
                visible_text = page.locator("body").inner_text(timeout=12000)
                visual_frame = ""
                try:
                    image_bytes = page.screenshot(
                        type="jpeg",
                        quality=65,
                        full_page=False,
                        animations="disabled",
                    )
                    if image_bytes:
                        visual_frame = base64.b64encode(image_bytes).decode("ascii")
                except Exception as error:
                    print("[SOCIAL POST SCREENSHOT ERROR]", repr(error))
                images = page.evaluate(
                    """
                    () => Array.from(document.images).map((image) => ({
                        url: image.currentSrc || image.src || '',
                        alt: image.alt || '',
                        width: image.naturalWidth || image.width || 0,
                        height: image.naturalHeight || image.height || 0,
                    })).filter((item) => item.url && item.width >= 240 && item.height >= 180)
                      .sort((a, b) => (b.width * b.height) - (a.width * a.height))
                      .slice(0, 8)
                    """
                )
                image_url = (
                    target["search_image_url"]
                    if target["search_image_url"].lower().startswith("https://")
                    else ""
                )
                if not image_url:
                    for image in images if isinstance(images, list) else []:
                        candidate = str(image.get("url") or "").strip()[:2048]
                        if candidate.lower().startswith("https://"):
                            image_url = candidate
                            break
                details.append(
                    {
                        **target,
                        "url": target["url"],
                        "visible_text": str(visible_text or "").strip()[:12000],
                        "image_url": image_url,
                        "visual_frame": visual_frame,
                    }
                )
            except Exception as error:
                print("[SOCIAL POST DETAIL ERROR]", repr(error))
                details.append(
                    {
                        **target,
                        "visible_text": target["search_visible_text"],
                        "image_url": target["search_image_url"],
                        "visual_frame": "",
                    }
                )
            finally:
                try:
                    page.close(run_before_unload=False)
                except Exception:
                    pass
    return details

def close_social_browser():
    """Close tabs in Bekki's dedicated social browser only."""

    from playwright.sync_api import sync_playwright

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
