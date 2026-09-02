"""Persistent local browser session for user-authorized social research."""

import base64
import hashlib
from html import unescape
from io import BytesIO
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
import managed_browser

CDP_PORT = managed_browser.CDP_PORT
CDP_URL = managed_browser.CDP_URL

SOCIAL_DOMAINS = {
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
    "xiaohongshu": ("xiaohongshu.com", "rednote.com"),
    "instagram": ("instagram.com",),
    "reddit": ("reddit.com", "redd.it"),
    "x": ("x.com", "twitter.com"),
}
MAX_VISUAL_FRAMES = 3
MAX_POST_CANDIDATES = 30
MAX_POST_DETAILS = 7
SOCIAL_SCREENSHOT_TIMEOUT_MS = 4500
SOCIAL_MEDIA_CACHE_MAX_FILES = 160
_BILIBILI_SEARCH_RESPONSE_CANDIDATES = {}


def _bilibili_search_cache_key(value):
    """Return a query-scoped key for one Bilibili search page."""

    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return ""
    parameters = parse_qs(parsed.query)
    keyword = parameters.get("keyword", [""])[0].strip()
    order = parameters.get("order", ["totalrank"])[0].strip()
    if not keyword:
        return ""
    return keyword.casefold() + "|" + order.casefold()


def _managed_social_browser_mode():
    """Return the mode of Bekki's one shared normal browser."""

    return managed_browser.browser_mode()


def _modern_edge_user_agent(browser_version):
    """Build an honest non-headless UA from the connected Edge version."""

    match = re.search(
        r"(?<!\d)(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?",
        str(browser_version or ""),
    )
    if not match:
        return ""
    parts = [match.group(index) or "0" for index in range(1, 5)]
    if int(parts[0]) < 100:
        return ""
    version = ".".join(parts)
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/" + version + " Safari/537.36 Edg/" + version
    )


def _apply_bilibili_browser_identity(browser, context, page):
    """Expose the real Edge version instead of its HeadlessChrome token."""

    user_agent = _modern_edge_user_agent(getattr(browser, "version", ""))
    if not user_agent:
        print("[SOCIAL BILIBILI UA] connected Edge version unavailable")
        return False
    session = None
    try:
        session = context.new_cdp_session(page)
        session.send(
            "Network.setUserAgentOverride",
            {
                "userAgent": user_agent,
                "acceptLanguage": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "platform": "Windows",
            },
        )
        print(
            "[SOCIAL BILIBILI UA]",
            "Edge/" + user_agent.rsplit("Edg/", 1)[-1],
        )
        return True
    except Exception as error:
        print("[SOCIAL BILIBILI UA ERROR]", repr(error))
        return False
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


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


def social_media_cache_dir():
    """Return Bekki's bounded local cache for user-visible social evidence."""

    path = app_data_dir() / "social_media_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prune_social_media_cache():
    """Keep recent evidence while preventing an unbounded image directory."""

    try:
        files = sorted(
            (
                item for item in social_media_cache_dir().iterdir()
                if item.is_file() and item.suffix.lower() in {".jpg", ".jpeg", ".png"}
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale in files[SOCIAL_MEDIA_CACHE_MAX_FILES:]:
            try:
                stale.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _persist_social_image_bytes(
    image_bytes,
    platform,
    source_url,
    post_title,
    image_index,
):
    """Persist one already-captured JPEG and return its absolute local path."""

    if not isinstance(image_bytes, (bytes, bytearray)):
        return ""
    image_bytes = bytes(image_bytes)
    if not image_bytes.startswith(b"\xff\xd8\xff") or len(image_bytes) > 8 * 1024 * 1024:
        return ""
    identity = "|".join(
        (
            str(platform or ""),
            str(source_url or ""),
            str(post_title or ""),
            str(image_index),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:24]
    destination = social_media_cache_dir() / (
        str(platform or "social")[:20] + "_" + digest + ".jpg"
    )
    try:
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(image_bytes)
        os.replace(temporary, destination)
        _prune_social_media_cache()
        return str(destination.resolve())
    except OSError as error:
        print("[SOCIAL IMAGE CACHE ERROR]", repr(error))
        return ""


def browser_profile_dir():
    return managed_browser.profile_dir()


def edge_executable():
    return managed_browser.edge_executable()


def cdp_is_ready():
    return managed_browser.cdp_is_ready()


def ensure_social_browser(headless=None):
    """Attach social research to Bekki's one shared normal Edge."""

    del headless
    managed_browser.ensure_browser()


def _reddit_time_filter(recency_days):
    try:
        days = max(int(recency_days or 0), 0)
    except (TypeError, ValueError):
        days = 0
    if not days:
        return "all"
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    if days <= 366:
        return "year"
    return "all"


def social_search_url(
    platform,
    query,
    selection_mode="RELEVANCE",
    ranking_mode="DEFAULT",
    recency_days=None,
):
    selection_mode = str(selection_mode or "RELEVANCE").strip().upper()
    if selection_mode not in {"RECENT", "RELEVANCE"}:
        selection_mode = "RELEVANCE"
    ranking_mode = str(ranking_mode or "DEFAULT").strip().upper()
    if ranking_mode not in {"DEFAULT", "DISCUSSION", "POPULARITY", "PRICE"}:
        ranking_mode = "DEFAULT"
    if platform == "bilibili":
        return (
            "https://search.bilibili.com/all?keyword="
            + quote(query)
            + ("&order=pubdate" if selection_mode == "RECENT" else "&order=totalrank")
        )

    if platform == "youtube":
        # An exact @handle + Shorts request has a stronger native boundary than
        # the general search grid: the channel's own Shorts tab. This prevents
        # fan uploads that merely mention the artist from outranking the
        # requested creator. Queries with any additional subject words remain
        # literal YouTube searches.
        handle_shorts = re.fullmatch(
            r"\s*@([A-Za-z0-9][A-Za-z0-9._-]{1,29})\s+"
            r"(?:youtube\s+)?shorts?\s*",
            str(query or ""),
            flags=re.IGNORECASE,
        )
        if handle_shorts:
            return (
                "https://www.youtube.com/@"
                + handle_shorts.group(1)
                + "/shorts"
            )
        # Keep the literal query intact. YouTube's rendered result cards carry
        # their own metadata; Bekki verifies a requested recency window against
        # the opened video's publication date when a grid card omits it.
        return "https://www.youtube.com/results?search_query=" + quote(query)

    if platform == "xiaohongshu":
        return (
            "https://www.rednote.com/search_result?keyword="
            + quote(query)
            + "&type=51"
        )

    if platform == "instagram":
        return "https://www.instagram.com/"

    if platform == "reddit":
        communities = re.findall(
            r"(?<![A-Za-z0-9_])r/([A-Za-z0-9_]{2,32})",
            str(query or ""),
            flags=re.IGNORECASE,
        )
        if len({value.casefold() for value in communities}) == 1:
            community = communities[0]
            scoped_query = re.sub(
                r"(?<![A-Za-z0-9_])r/[A-Za-z0-9_]{2,32}",
                " ",
                str(query or ""),
                flags=re.IGNORECASE,
            )
            scoped_query = " ".join(scoped_query.split()) or str(query or "")
            sort_value = (
                "comments" if ranking_mode == "DISCUSSION"
                else "top" if ranking_mode == "POPULARITY"
                else "new" if selection_mode == "RECENT"
                else "relevance"
            )
            time_value = (
                "&t=" + _reddit_time_filter(recency_days)
                if ranking_mode != "DEFAULT" else ""
            )
            return (
                "https://www.reddit.com/r/" + community + "/search/?q="
                + quote(scoped_query)
                + "&restrict_sr=1"
                + "&sort=" + sort_value
                + time_value
            )
        sort_value = (
            "comments" if ranking_mode == "DISCUSSION"
            else "top" if ranking_mode == "POPULARITY"
            else "new" if selection_mode == "RECENT"
            else "relevance"
        )
        time_value = (
            "&t=" + _reddit_time_filter(recency_days)
            if ranking_mode != "DEFAULT" else ""
        )
        return (
            "https://www.reddit.com/search/?q="
            + quote(query)
            + "&sort=" + sort_value
            + time_value
        )

    if platform == "x":
        return (
            "https://x.com/search?q="
            + quote(query)
            + "&src=typed_query"
            + ("&f=live" if selection_mode == "RECENT" else "")
        )

    raise ValueError("Unsupported social platform: " + str(platform))


def _dismiss_youtube_consent(page):
    """Dismiss only YouTube's bounded cookie choice, never sign-in controls."""

    labels = (
        "Reject all",
        "全部拒绝",
        "拒绝全部",
        "Alle ablehnen",
        "Tout refuser",
        "Accept all",
        "接受全部",
        "全部接受",
        "Alle akzeptieren",
        "Tout accepter",
    )
    try:
        return bool(
            page.evaluate(
                r"""
                (labels) => {
                    const normalize = (value) => (value || '')
                        .replace(/\s+/g, ' ').trim().toLocaleLowerCase();
                    const wanted = labels.map(normalize);
                    const controls = Array.from(document.querySelectorAll(
                        'button, [role="button"], input[type="submit"]'
                    ));
                    for (const control of controls) {
                        const text = normalize(
                            control.innerText || control.value ||
                            control.getAttribute('aria-label') || ''
                        );
                        if (!text || !wanted.includes(text)) continue;
                        const rect = control.getBoundingClientRect();
                        if (rect.width < 2 || rect.height < 2) continue;
                        control.click();
                        return true;
                    }
                    return false;
                }
                """,
                list(labels),
            )
        )
    except Exception:
        return False


def open_social_search(
    platform,
    query,
    selection_mode="RELEVANCE",
    ranking_mode="DEFAULT",
    recency_days=None,
):
    """Open a social search in Bekki's managed Edge session."""

    from playwright.sync_api import (
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
    )

    ensure_social_browser()
    target_url = social_search_url(
        platform,
        query,
        selection_mode,
        ranking_mode=ranking_mode,
        recency_days=recency_days,
    )

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
        managed_browser.keep_page_background(context, page)

        if platform == "bilibili":
            _apply_bilibili_browser_identity(browser, context, page)
            cache_key = _bilibili_search_cache_key(target_url)
            if cache_key:
                _BILIBILI_SEARCH_RESPONSE_CANDIDATES.pop(cache_key, None)
                page.on(
                    "response",
                    lambda response: _store_bilibili_search_response(
                        cache_key, response
                    ),
                )

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
        if platform == "youtube":
            try:
                page.wait_for_timeout(650)
            except Exception:
                pass
            consent_handled = _dismiss_youtube_consent(page)
            if consent_handled:
                try:
                    page.wait_for_timeout(900)
                except Exception:
                    pass
            if not matches_expected_social_search(page.url, target_url):
                # A consent interstitial may finish without restoring the
                # original search URL. Re-open the same bounded destination
                # once after the user's persisted reject/accept choice.
                try:
                    page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=8000,
                    )
                except PlaywrightTimeoutError:
                    print("[SOCIAL YOUTUBE NAVIGATION CONTINUES]", target_url)
            try:
                page.wait_for_timeout(1800)
            except Exception:
                pass
        if platform == "bilibili":
            # The page's own structured search response often arrives after
            # DOMContentLoaded. Keep the event listener connected briefly.
            page.wait_for_timeout(3500)

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
    compared_query = False
    for key in ("q", "keyword", "search_query"):
        expected_query = expected_parameters.get(key, [""])[0].strip()
        if not expected_query:
            continue
        actual_query = actual_parameters.get(key, [""])[0].strip()
        if actual_query != expected_query:
            return False
        compared_query = True
    for key in ("sort", "order", "f", "t", "restrict_sr"):
        expected_value = expected_parameters.get(key, [""])[0].strip()
        if not expected_value:
            continue
        actual_value = actual_parameters.get(key, [""])[0].strip()
        if actual_value != expected_value:
            return False
    if compared_query:
        return True
    return True


_YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,32}$")


def _canonical_youtube_video_url(value):
    """Return one canonical public YouTube video/Shorts URL."""

    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        return ""
    video_id = ""
    kind = "watch"
    if hostname == "youtu.be" or hostname.endswith(".youtu.be"):
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif hostname in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:
        path_parts = [part for part in parsed.path.split("/") if part]
        lowered_parts = [part.casefold() for part in path_parts]
        if parsed.path.rstrip("/").casefold() == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        elif len(path_parts) >= 2 and lowered_parts[0] in {"shorts", "live"}:
            kind = lowered_parts[0]
            video_id = path_parts[1]
        else:
            return ""
    else:
        return ""
    if not _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
        return ""
    if kind in {"shorts", "live"}:
        return "https://www.youtube.com/" + kind + "/" + video_id
    return "https://www.youtube.com/watch?v=" + video_id


def _youtube_video_identity(value):
    """Return the video ID so Shorts/watch redirects can be compared safely."""

    canonical = _canonical_youtube_video_url(value)
    if not canonical:
        return ""
    parsed = urlparse(canonical)
    if parsed.path == "/watch":
        return parse_qs(parsed.query).get("v", [""])[0]
    return parsed.path.rstrip("/").rsplit("/", 1)[-1]


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
    if platform == "bilibili":
        if hostname == "b23.tv":
            if path in ("", "/"):
                return ""
        elif hostname == "space.bilibili.com":
            if not path.strip("/").isdigit():
                return ""
        elif hostname == "t.bilibili.com":
            if not path.strip("/").isdigit():
                return ""
        elif hostname == "live.bilibili.com":
            if not path.strip("/").split("/", 1)[0].isdigit():
                return ""
        elif hostname in ("bilibili.com", "www.bilibili.com"):
            if not any(
                path.startswith(marker)
                for marker in (
                    "/bangumi/play/",
                    "/opus/",
                    "/read/",
                    "/video/",
                )
            ):
                return ""
        else:
            return ""
    if platform == "youtube":
        return _canonical_youtube_video_url(value)
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
    if platform == "reddit":
        if hostname == "redd.it":
            if path in ("", "/"):
                return ""
        elif "/comments/" not in path:
            return ""
    return str(value).strip()[:2048]


def _allowed_social_page_url(platform, value):
    """Allow a public platform page as a bounded search-card source."""

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
    if platform == "youtube":
        if _canonical_youtube_video_url(value):
            return str(value).strip()[:2048]
        path = parsed.path.rstrip("/")
        if path == "/results":
            if not parse_qs(parsed.query).get("search_query", [""])[0].strip():
                return ""
        else:
            channel_tab = re.fullmatch(
                r"/@([A-Za-z0-9][A-Za-z0-9._-]{1,29})/"
                r"(shorts|videos|streams)",
                path,
                flags=re.IGNORECASE,
            )
            if not channel_tab:
                return ""
    return str(value).strip()[:2048]


def _normalize_social_image_url(platform, value):
    """Return a usable HTTPS image URL without changing its source image."""

    value = str(value or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or not hostname:
        return ""
    if platform == "bilibili" and (
        hostname == "hdslb.com" or hostname.endswith(".hdslb.com")
    ):
        # Bilibili search cards commonly expose a transformed AVIF URL such as
        # ``cover.jpg@672w_378h_1c_!web-search-common-cover.avif``. Qt builds
        # without an AVIF plugin cannot render it, while the original JPEG is
        # available at the same URL before the transformation suffix.
        lowered = value.lower()
        for extension in (".jpeg", ".jpg", ".png", ".webp"):
            marker = extension + "@"
            marker_index = lowered.find(marker)
            if marker_index >= 0:
                value = value[: marker_index + len(extension)]
                break
    return value[:2048]


def _capture_page_jpeg(page, quality=68, timeout_ms=SOCIAL_SCREENSHOT_TIMEOUT_MS):
    """Capture quickly, bypassing Playwright's long font wait when necessary."""

    try:
        return page.screenshot(
            type="jpeg",
            quality=min(max(int(quality or 68), 35), 90),
            full_page=False,
            animations="disabled",
            timeout=min(max(int(timeout_ms or 0), 1000), 8000),
        )
    except Exception as playwright_error:
        print(
            "[SOCIAL SCREENSHOT FALLBACK]",
            "reason=" + type(playwright_error).__name__,
        )
    session = None
    try:
        session = page.context.new_cdp_session(page)
        result = session.send(
            "Page.captureScreenshot",
            {
                "format": "jpeg",
                "quality": min(max(int(quality or 68), 35), 90),
                "fromSurface": True,
                "captureBeyondViewport": False,
            },
        )
        return base64.b64decode(str(result.get("data") or ""), validate=True)
    except Exception as cdp_error:
        print("[SOCIAL SCREENSHOT ERROR]", repr(cdp_error))
        return b""
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def _capture_locator_jpeg(
    page,
    locator,
    quality=78,
    timeout_ms=SOCIAL_SCREENSHOT_TIMEOUT_MS,
):
    try:
        return locator.screenshot(
            type="jpeg",
            quality=min(max(int(quality or 78), 35), 90),
            animations="disabled",
            timeout=min(max(int(timeout_ms or 0), 1000), 8000),
        )
    except Exception:
        try:
            box = locator.bounding_box()
        except Exception:
            box = None
        return _capture_clip_jpeg(page, box, quality=quality)


def _capture_clip_jpeg(page, clip, quality=76):
    if not isinstance(clip, dict):
        return b""
    try:
        x = max(float(clip.get("x") or 0), 0.0)
        y = max(float(clip.get("y") or 0), 0.0)
        width = min(max(float(clip.get("width") or 0), 1.0), 2400.0)
        height = min(max(float(clip.get("height") or 0), 1.0), 2400.0)
    except (TypeError, ValueError):
        return b""
    if width < 80 or height < 60:
        return b""
    session = None
    try:
        session = page.context.new_cdp_session(page)
        result = session.send(
            "Page.captureScreenshot",
            {
                "format": "jpeg",
                "quality": min(max(int(quality or 76), 35), 90),
                "fromSurface": True,
                "captureBeyondViewport": True,
                "clip": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "scale": 1,
                },
            },
        )
        return base64.b64decode(str(result.get("data") or ""), validate=True)
    except Exception:
        return b""
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


def _normalize_raster_to_jpeg(image_bytes, quality=84):
    """Decode a bounded web raster and return a Qt-friendly JPEG."""

    if not isinstance(image_bytes, (bytes, bytearray)):
        return b""
    image_bytes = bytes(image_bytes)
    if not image_bytes or len(image_bytes) > 16 * 1024 * 1024:
        return b""
    try:
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as source:
            source.load()
            if source.width < 80 or source.height < 60:
                return b""
            image = source.convert("RGB")
            image.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
            destination = BytesIO()
            image.save(
                destination,
                format="JPEG",
                quality=min(max(int(quality or 84), 55), 90),
                optimize=True,
            )
            value = destination.getvalue()
            return value if len(value) <= 8 * 1024 * 1024 else b""
    except Exception:
        return b""


def _meaningful_raster_evidence(image_bytes):
    """Reject blank/loading rasters before they become visible evidence."""

    if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
        return False
    try:
        from PIL import Image

        with Image.open(BytesIO(bytes(image_bytes))) as source:
            image = source.convert("RGB")
            if image.width < 160 or image.height < 90:
                return False
            image.thumbnail((96, 96), Image.Resampling.LANCZOS)
            pixels = (
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )
            luminance = [
                (299 * red + 587 * green + 114 * blue) / 1000
                for red, green, blue in pixels
            ]
    except Exception:
        return False
    if not luminance:
        return False
    sample_count = len(luminance)
    mean = sum(luminance) / sample_count
    variance = sum((value - mean) ** 2 for value in luminance) / sample_count
    light_fraction = sum(value >= 247 for value in luminance) / sample_count
    # Bilibili's unloaded player is almost entirely black with one tiny TV
    # glyph.  White/grey skeleton pages are the inverse of the same problem.
    if sum(value <= 32 for value in luminance) / sample_count >= 0.94 and mean < 38:
        return False
    if light_fraction >= 0.97 and variance < 95:
        return False
    return variance >= 18


def _detailed_raster_evidence(image_bytes):
    """Reject deliberately blurred/placeholder media before UI rendering.

    A search-card screenshot can contain sharp author/date text around a fully
    blurred thumbnail, so this check must run on the media raster itself.  The
    bounded adjacent-pixel energy distinguishes a decoded photograph/frame
    from Xiaohongshu's low-frequency placeholder without trying to identify
    its subject.
    """

    if not _meaningful_raster_evidence(image_bytes):
        return False
    try:
        from PIL import Image

        with Image.open(BytesIO(bytes(image_bytes))) as source:
            image = source.convert("L")
            image.thumbnail((160, 160), Image.Resampling.LANCZOS)
            width, height = image.size
            if width < 80 or height < 60:
                return False
            pixels = list(
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )
    except Exception:
        return False
    if not pixels:
        return False
    horizontal = sum(
        abs(pixels[row * width + column] - pixels[row * width + column - 1])
        for row in range(height)
        for column in range(1, width)
    )
    vertical = sum(
        abs(pixels[row * width + column] - pixels[(row - 1) * width + column])
        for row in range(1, height)
        for column in range(width)
    )
    comparisons = height * (width - 1) + (height - 1) * width
    edge_energy = (horizontal + vertical) / max(comparisons, 1)
    ordered = sorted(pixels)
    dynamic_range = (
        ordered[int(len(ordered) * 0.95)]
        - ordered[int(len(ordered) * 0.05)]
    )
    return edge_energy >= 2.15 and dynamic_range >= 16


def _raster_difference_hash(image_bytes):
    """Return a small perceptual hash for duplicate cover/frame filtering."""

    try:
        from PIL import Image

        with Image.open(BytesIO(bytes(image_bytes))) as source:
            image = source.convert("L").resize(
                (9, 8), Image.Resampling.LANCZOS
            )
            pixels = list(
                image.get_flattened_data()
                if hasattr(image, "get_flattened_data")
                else image.getdata()
            )
    except Exception:
        return None
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value <<= 1
            if pixels[offset + column] > pixels[offset + column + 1]:
                value |= 1
    return value


def _raster_is_distinct(image_bytes, known_hashes, maximum_distance=4):
    fingerprint = _raster_difference_hash(image_bytes)
    if fingerprint is None:
        return False
    for known in known_hashes:
        if (fingerprint ^ known).bit_count() <= maximum_distance:
            return False
    known_hashes.append(fingerprint)
    return True


def _download_post_image_jpeg(page, image_url):
    """Fetch one already-visible post image through the browser session."""

    image_url = str(image_url or "").strip()
    if not image_url.lower().startswith("https://"):
        return b""
    try:
        response = page.context.request.get(
            image_url,
            headers={"Referer": str(page.url or "")[:2048]},
            timeout=7000,
            fail_on_status_code=False,
        )
        if not (200 <= int(response.status) < 300):
            return b""
        return _normalize_raster_to_jpeg(response.body())
    except Exception:
        return b""


def _locator_visible_text(locator, limit=6000):
    try:
        return " ".join(str(locator.inner_text(timeout=1500) or "").split())[
            :max(int(limit or 0), 0)
        ]
    except Exception:
        return ""


def _first_post_text_container(page, platform):
    """Find a post body, never a site-wide login or navigation shell."""

    for selector in _post_container_selectors(platform):
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 10)):
                locator = locators.nth(index)
                box = locator.bounding_box()
                if not isinstance(box, dict):
                    continue
                width = float(box.get("width") or 0)
                height = float(box.get("height") or 0)
                text = _locator_visible_text(locator)
                lowered = text.casefold()
                if width < 280 or height < 100 or len(text) < 18:
                    continue
                if (
                    "continue with google" in lowered
                    or "about rednote terms of service" in lowered
                ):
                    continue
                return locator
        except Exception:
            continue
    return None


def _bounded_reddit_post_text(page):
    """Read one Reddit post body plus at most two visible comments."""

    container = _first_post_text_container(page, "reddit")
    body = _locator_visible_text(container, 7000) if container is not None else ""
    comments = []
    for selector in (
        "shreddit-comment",
        '[data-testid="comment"]',
        '[slot="comment"]',
    ):
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 4)):
                text = _locator_visible_text(locators.nth(index), 1200)
                if text and text not in comments:
                    comments.append(text)
                if len(comments) >= 2:
                    break
        except Exception:
            continue
        if len(comments) >= 2:
            break
    parts = []
    if body:
        parts.append("POST BODY: " + body)
    for index, comment in enumerate(comments, start=1):
        parts.append("VISIBLE COMMENT " + str(index) + ": " + comment)
    return "\n".join(parts)[:10000]


_XIAOHONGSHU_VISIBLE_TIME_PATTERN = re.compile(
    r"(?:"
    r"刚刚|\d+\s*(?:分钟|小时|天)前|今天|昨天|前天|"
    r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?|"
    r"\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}"
    r"(?:,?\s+\d{4})?|"
    r"just\s+now|today|yesterday|\d+\s*(?:minutes?|hours?|days?)\s+ago"
    r")",
    flags=re.IGNORECASE,
)


def _visible_social_time_in_text(value):
    match = _XIAOHONGSHU_VISIBLE_TIME_PATTERN.search(str(value or "")[:1600])
    return " ".join(match.group(0).split())[:80] if match else ""


def _xiaohongshu_visible_post_time(page):
    """Read a date/time only from the opened note's own bounded container."""

    candidates = []
    selectors = (
        "#detail-date",
        "#detail-time",
        '.note-content time',
        '.note-content [class*="date"]',
        '.note-content [class*="time"]',
        '[class*="note-content"] time',
        '[class*="note-content"] [class*="date"]',
        '[class*="note-content"] [class*="time"]',
        '[class*="detail-content"] time',
        '[class*="detail-content"] [class*="date"]',
        '[class*="detail-content"] [class*="time"]',
    )
    for selector in selectors:
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 8)):
                value = _locator_visible_text(locators.nth(index), 120)
                if value:
                    candidates.append(value)
        except Exception:
            continue
    container = _first_post_text_container(page, "xiaohongshu")
    if container is not None:
        try:
            raw_text = str(container.inner_text(timeout=1800) or "")
        except Exception:
            raw_text = ""
        candidates.extend(
            line.strip() for line in raw_text.splitlines() if line.strip()
        )
    for value in candidates:
        visible_time = _visible_social_time_in_text(str(value)[:240])
        if visible_time:
            return visible_time
    return ""


def _bounded_xiaohongshu_post_text(page):
    """Read only the current Rednote note, excluding related-note shelves.

    Xiaohongshu detail pages commonly keep recommendations in the same page
    ``body`` as the opened note.  Prefer the note's title/description nodes and
    then fall back to the first bounded note container.  This keeps a model
    from summarising neighbouring search suggestions as if they belonged to
    the current author.
    """

    parts = []
    seen = set()
    for selector in (
        "#detail-title",
        "#detail-desc",
        '.note-content [class*="title"]',
        '.note-content [class*="desc"]',
        '[class*="note-content"] [class*="title"]',
        '[class*="note-content"] [class*="desc"]',
    ):
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 4)):
                text = _locator_visible_text(locators.nth(index), 3200)
                key = " ".join(text.casefold().split())
                if len(text) < 2 or not key or key in seen:
                    continue
                seen.add(key)
                parts.append(text)
        except Exception:
            continue
    if not parts:
        container = _first_post_text_container(page, "xiaohongshu")
        text = (
            _locator_visible_text(container, 7000)
            if container is not None else ""
        )
        if text:
            parts.append(text)
    if not parts:
        # Compatibility fallback for a compact standalone detail document.
        # A real search/login shell is much larger and carries several of the
        # following navigation markers, so it must never become note text.
        try:
            body_text = _locator_visible_text(page.locator("body"), 1600)
        except Exception:
            body_text = ""
        lowered = body_text.casefold()
        shell_markers = (
            "search rednote",
            "about rednote",
            "terms of service",
            "相关推荐",
            "探索",
            "通知",
            "登录",
        )
        if (
            4 <= len(body_text) <= 1200
            and sum(marker in lowered for marker in shell_markers) < 2
        ):
            parts.append(body_text)
    if not parts:
        return ""
    visible_time = _xiaohongshu_visible_post_time(page)
    if visible_time:
        parts.append("VISIBLE PUBLISHED TIME: " + visible_time)
    return ("CURRENT NOTE:\n" + "\n".join(parts))[:8000]


def _bilibili_video_metadata(page):
    """Read current-video metadata without touching the recommendation rail."""

    try:
        payload = page.evaluate(
            r"""
            () => {
                const state = window.__INITIAL_STATE__ || {};
                const video = state.videoData || state.videoInfo || {};
                const owner = video.owner || {};
                const meta = (selector) => {
                    const node = document.querySelector(selector);
                    return node ? (node.content || node.getAttribute('content') || '') : '';
                };
                const playerVideo = document.querySelector(
                    '#bilibili-player video, .bpx-player-video-wrap video, video'
                );
                return {
                    title: video.title || meta('meta[property="og:title"]') || '',
                    description: video.desc || meta('meta[name="description"]') || '',
                    author: owner.name || meta('meta[name="author"]') || '',
                    cover: video.pic || meta('meta[property="og:image"]') ||
                        meta('meta[itemprop="image"]') ||
                        (playerVideo ? (playerVideo.poster || '') : ''),
                    published_at: video.pubdate || video.ctime ||
                        meta('meta[itemprop="uploadDate"]') || '',
                    bvid: video.bvid || state.bvid || '',
                };
            }
            """
        )
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_bilibili_video_text(page, expected_title=""):
    """Read only the current Bilibili video's title, author and description."""

    metadata = _bilibili_video_metadata(page)
    parts = []
    seen = set()

    def add(label, value, limit):
        text = " ".join(str(value or "").split()).strip()[:limit]
        text = re.sub(r"[_\- ]*哔哩哔哩(?:_bilibili)?\s*$", "", text)
        key = text.casefold()
        if not text or key in seen:
            return
        seen.add(key)
        parts.append(label + ": " + text)

    add("标题", metadata.get("title") or expected_title, 500)
    add("UP主", metadata.get("author"), 220)
    published_at = metadata.get("published_at")
    if isinstance(published_at, (int, float)) or str(published_at).isdigit():
        try:
            published_at = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(int(published_at))
            )
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    add("发布时间", published_at, 80)
    add("简介", metadata.get("description"), 3600)

    selector_fields = (
        ("h1.video-title", "标题", 500),
        (".video-title", "标题", 500),
        (".up-name", "UP主", 220),
        (".desc-info-text", "简介", 3600),
        (".basic-desc-info", "简介", 3600),
        (".video-desc-container", "简介", 3600),
        (".desc-v2", "简介", 3600),
    )
    for selector, label, limit in selector_fields:
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 3)):
                add(label, _locator_visible_text(locators.nth(index), limit), limit)
        except Exception:
            continue
    if not parts and expected_title:
        add("标题", expected_title, 500)
    return ("CURRENT VIDEO:\n" + "\n".join(parts))[:7000] if parts else ""


def _bilibili_cover_urls(page, fallback_image_url=""):
    """Return bounded cover candidates for the current opened Bilibili video."""

    candidates = [fallback_image_url, _bilibili_video_metadata(page).get("cover")]
    try:
        candidates.extend(
            page.evaluate(
                r"""
                () => Array.from(document.querySelectorAll(
                    'meta[property="og:image"], meta[itemprop="image"], video[poster]'
                )).map((node) => node.content || node.poster || '')
                """
            ) or []
        )
    except Exception:
        pass
    output = []
    seen = set()
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if candidate.startswith("http://"):
            candidate = "https://" + candidate[len("http://"):]
        candidate = _normalize_social_image_url("bilibili", candidate)
        try:
            hostname = str(urlparse(candidate).hostname or "").lower()
        except ValueError:
            continue
        if not candidate or not (
            hostname == "hdslb.com"
            or hostname.endswith(".hdslb.com")
            or hostname == "biliimg.com"
            or hostname.endswith(".biliimg.com")
        ):
            continue
        key = candidate.split("?", 1)[0].casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output[:4]


def _capture_bilibili_video_frame(page):
    """Decode and capture one real player frame; return nothing on black/loading."""

    selectors = (
        "#bilibili-player video",
        ".bpx-player-video-wrap video",
        "video",
    )
    video = None
    for selector in selectors:
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 3)):
                locator = locators.nth(index)
                box = locator.bounding_box()
                if not isinstance(box, dict):
                    continue
                if float(box.get("width") or 0) < 320 or float(
                    box.get("height") or 0
                ) < 180:
                    continue
                video = locator
                break
        except Exception:
            continue
        if video is not None:
            break
    if video is None:
        return b""
    try:
        encoded = video.evaluate(
            r"""
            async (node) => {
                const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const eventOrDelay = (name, ms) => Promise.race([
                    new Promise((resolve) => node.addEventListener(
                        name, resolve, {once: true}
                    )),
                    delay(ms),
                ]);
                node.muted = true;
                node.volume = 0;
                node.playsInline = true;
                if (node.readyState < 2) await eventOrDelay('loadeddata', 2200);
                try { await node.play(); } catch (_error) {}
                if (Number.isFinite(node.duration) && node.duration > 6) {
                    const target = Math.min(Math.max(node.duration * 0.08, 2), 18);
                    if (Math.abs((node.currentTime || 0) - target) > 1) {
                        try {
                            node.currentTime = target;
                            await eventOrDelay('seeked', 2200);
                        } catch (_error) {}
                    }
                }
                await delay(450);
                if (node.readyState < 2 || !node.videoWidth || !node.videoHeight) {
                    return '';
                }
                const width = Math.min(node.videoWidth, 1280);
                const height = Math.max(
                    1, Math.round(width * node.videoHeight / node.videoWidth)
                );
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext('2d', {alpha: false});
                if (!context) return '';
                try {
                    context.drawImage(node, 0, 0, width, height);
                    return canvas.toDataURL('image/jpeg', 0.82);
                } catch (_error) {
                    return '';
                }
            }
            """
        )
    except Exception:
        encoded = ""
    image_bytes = b""
    if isinstance(encoded, str) and encoded.startswith("data:image/jpeg;base64,"):
        try:
            image_bytes = _normalize_raster_to_jpeg(
                base64.b64decode(encoded.split(",", 1)[1], validate=True),
                quality=84,
            )
        except (TypeError, ValueError):
            image_bytes = b""
    if not image_bytes:
        image_bytes = _capture_locator_jpeg(page, video, quality=82)
    return image_bytes if _meaningful_raster_evidence(image_bytes) else b""


def _youtube_video_metadata(page):
    """Read the current YouTube video/Short without recommendation text."""

    try:
        payload = page.evaluate(
            r"""
            () => {
                const response = window.ytInitialPlayerResponse || {};
                const details = response.videoDetails || {};
                const micro = (
                    response.microformat &&
                    response.microformat.playerMicroformatRenderer
                ) || {};
                const meta = (selector) => {
                    const node = document.querySelector(selector);
                    return node ? (
                        node.content || node.getAttribute('content') || ''
                    ) : '';
                };
                const text = (selector, root = document) => {
                    const node = root.querySelector(selector);
                    return node ? (
                        node.innerText || node.textContent || ''
                    ).replace(/\s+/g, ' ').trim() : '';
                };
                const rendererText = (value) => {
                    if (!value) return '';
                    if (typeof value === 'string') return value;
                    if (value.simpleText) return value.simpleText;
                    if (Array.isArray(value.runs)) {
                        return value.runs.map((run) => run.text || '').join('');
                    }
                    return '';
                };
                const activeShort = document.querySelector(
                    'ytd-reel-video-renderer[is-active], ' +
                    'ytd-reel-video-renderer[aria-hidden="false"]'
                );
                const scope = activeShort || document;
                const thumbnailRows = [];
                const collect = (rows) => {
                    for (const row of (Array.isArray(rows) ? rows : [])) {
                        if (!row || !row.url) continue;
                        thumbnailRows.push({
                            url: row.url,
                            width: Number(row.width || 0),
                            height: Number(row.height || 0),
                        });
                    }
                };
                collect(details.thumbnail && details.thumbnail.thumbnails);
                collect(micro.thumbnail && micro.thumbnail.thumbnails);
                thumbnailRows.sort((left, right) => (
                    right.width * right.height - left.width * left.height
                ));
                const playerVideo = scope.querySelector(
                    'video.html5-main-video, video'
                ) || document.querySelector(
                    '#movie_player video.html5-main-video, video.html5-main-video'
                );
                const visibleTitle = text(
                    'h1 yt-formatted-string, h1.title, #title yt-formatted-string, ' +
                    '#title, h2', scope
                );
                const scopedAuthorSelector = activeShort ? (
                    'ytd-reel-player-overlay-renderer #channel-name a, ' +
                    'yt-reel-channel-bar-view-model a[href^="/@"], ' +
                    '#channel-name a, a.yt-simple-endpoint[href^="/@"], ' +
                    'a[href^="/@"]'
                ) : (
                    'ytd-video-owner-renderer #channel-name a, ' +
                    '#owner #channel-name a, ytd-channel-name a'
                );
                const authorNode = scope.querySelector(scopedAuthorSelector) ||
                    document.querySelector(
                        'ytd-watch-metadata ytd-video-owner-renderer ' +
                        '#channel-name a, #owner #channel-name a'
                    );
                const visibleAuthor = authorNode ? (
                    authorNode.innerText || authorNode.textContent || ''
                ).replace(/\s+/g, ' ').trim() : '';
                const channelId = details.channelId || micro.externalChannelId || '';
                const findCurrentChannelRoute = () => {
                    if (!channelId || !window.ytInitialData) return '';
                    const stack = [window.ytInitialData];
                    const seen = new Set();
                    let inspected = 0;
                    while (stack.length && inspected < 25000) {
                        const value = stack.pop();
                        if (!value || typeof value !== 'object' || seen.has(value)) {
                            continue;
                        }
                        seen.add(value);
                        inspected += 1;
                        const endpoint = value.browseEndpoint || {};
                        if (endpoint.browseId === channelId) {
                            const candidates = [
                                endpoint.canonicalBaseUrl,
                                value.commandMetadata &&
                                    value.commandMetadata.webCommandMetadata &&
                                    value.commandMetadata.webCommandMetadata.url,
                            ];
                            const matched = candidates.find((candidate) =>
                                typeof candidate === 'string' &&
                                /^\/@[A-Za-z0-9._-]+(?:\/|$)/.test(candidate)
                            );
                            if (matched) return matched;
                        }
                        for (const child of Object.values(value)) {
                            if (child && typeof child === 'object') stack.push(child);
                        }
                    }
                    return '';
                };
                const channelUrl = (
                    (authorNode && (
                        authorNode.href || authorNode.getAttribute('href')
                    )) || findCurrentChannelRoute() || micro.ownerProfileUrl || ''
                );
                const handleMatch = String(channelUrl).match(
                    /(?:youtube\.com)?\/@([A-Za-z0-9._-]+)/i
                );
                const visibleDescription = text(
                    '#description-inline-expander, #description, ' +
                    'ytd-text-inline-expander', scope
                ) || text(
                    '#description-inline-expander, ' +
                    'ytd-text-inline-expander#description-inline-expander'
                );
                return {
                    title: details.title ||
                        rendererText(micro.title) || visibleTitle ||
                        meta('meta[property="og:title"]') || '',
                    description: details.shortDescription ||
                        rendererText(micro.description) || visibleDescription ||
                        meta('meta[name="description"]') || '',
                    author: details.author || micro.ownerChannelName ||
                        visibleAuthor || meta('meta[name="author"]') || '',
                    channel_id: channelId,
                    channel_url: channelUrl,
                    channel_handle: handleMatch ? ('@' + handleMatch[1]) : '',
                    cover: (thumbnailRows[0] && thumbnailRows[0].url) ||
                        meta('meta[property="og:image"]') ||
                        meta('meta[itemprop="thumbnailUrl"]') ||
                        (playerVideo ? (playerVideo.poster || '') : ''),
                    thumbnail_urls: thumbnailRows.map((row) => row.url).slice(0, 8),
                    published_at: micro.publishDate || micro.uploadDate ||
                        meta('meta[itemprop="datePublished"]') ||
                        meta('meta[itemprop="uploadDate"]') || '',
                    video_id: details.videoId ||
                        meta('meta[itemprop="videoId"]') || '',
                    is_short: location.pathname.toLowerCase().startsWith('/shorts/'),
                };
            }
            """
        )
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_youtube_video_text(page, expected_title="", metadata=None):
    """Read only the opened YouTube video's own title/channel/description."""

    metadata = metadata if isinstance(metadata, dict) else _youtube_video_metadata(page)
    parts = []
    seen = set()

    def add(label, value, limit):
        text = " ".join(str(value or "").split()).strip()[:limit]
        text = re.sub(r"\s*[-|]\s*YouTube\s*$", "", text, flags=re.IGNORECASE)
        key = text.casefold()
        if not text or key in seen:
            return
        seen.add(key)
        parts.append(label + ": " + text)

    add("标题", metadata.get("title") or expected_title, 500)
    add("频道", metadata.get("author"), 220)
    add("频道账号", metadata.get("channel_handle"), 80)
    add("发布时间", metadata.get("published_at"), 80)
    add("简介", metadata.get("description"), 3600)
    if not parts and expected_title:
        add("标题", expected_title, 500)
    return ("CURRENT VIDEO:\n" + "\n".join(parts))[:7000] if parts else ""


def _youtube_published_time(metadata):
    """Return an ISO date from current-video metadata when available."""

    value = str(
        metadata.get("published_at") if isinstance(metadata, dict) else ""
    ).strip()
    match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", value)
    return match.group(1) if match else _visible_social_time_in_text(value)


def _youtube_cover_urls(page, fallback_image_url="", metadata=None):
    """Return native thumbnails bound to the current YouTube video only."""

    metadata = metadata if isinstance(metadata, dict) else _youtube_video_metadata(page)
    candidates = [metadata.get("cover")]
    candidates.extend(
        metadata.get("thumbnail_urls", [])
        if isinstance(metadata.get("thumbnail_urls"), list) else []
    )
    candidates.append(fallback_image_url)
    try:
        candidates.extend(
            page.evaluate(
                r"""
                () => Array.from(document.querySelectorAll(
                    'meta[property="og:image"], ' +
                    'meta[itemprop="thumbnailUrl"], video[poster]'
                )).map((node) => (
                    node.content || node.poster || node.getAttribute('content') || ''
                ))
                """
            ) or []
        )
    except Exception:
        pass
    output = []
    seen = set()
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        if candidate.startswith("http://"):
            candidate = "https://" + candidate[len("http://"):]
        candidate = _normalize_social_image_url("youtube", candidate)
        try:
            hostname = str(urlparse(candidate).hostname or "").lower()
        except ValueError:
            continue
        if not candidate or not (
            hostname == "ytimg.com"
            or hostname.endswith(".ytimg.com")
            or hostname == "img.youtube.com"
        ):
            continue
        key = candidate.split("?", 1)[0].casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output[:5]


def _capture_youtube_video_frame(page):
    """Capture one decoded current-video frame, excluding ads and page chrome."""

    selectors = (
        'ytd-reel-video-renderer[is-active] video',
        'ytd-reel-video-renderer[aria-hidden="false"] video',
        'ytd-shorts video.html5-main-video',
        '#movie_player video.html5-main-video',
        'video.html5-main-video',
    )
    video = None
    for selector in selectors:
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 4)):
                locator = locators.nth(index)
                box = locator.bounding_box()
                if not isinstance(box, dict):
                    continue
                if float(box.get("width") or 0) < 240 or float(
                    box.get("height") or 0
                ) < 180:
                    continue
                video = locator
                break
        except Exception:
            continue
        if video is not None:
            break
    if video is None:
        return b""
    try:
        ad_showing = bool(
            video.evaluate(
                r"""
                (node) => Boolean(
                    node.closest('#movie_player.ad-showing, .ad-showing')
                )
                """
            )
        )
    except Exception:
        ad_showing = False
    if ad_showing:
        print("[SOCIAL YOUTUBE FRAME SKIPPED] reason=ad_showing")
        return b""
    try:
        encoded = video.evaluate(
            r"""
            async (node) => {
                const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                const eventOrDelay = (name, ms) => Promise.race([
                    new Promise((resolve) => node.addEventListener(
                        name, resolve, {once: true}
                    )),
                    delay(ms),
                ]);
                node.muted = true;
                node.volume = 0;
                node.playsInline = true;
                if (node.readyState < 2) await eventOrDelay('loadeddata', 2600);
                try { await node.play(); } catch (_error) {}
                if (Number.isFinite(node.duration) && node.duration > 5) {
                    const target = Math.min(Math.max(node.duration * 0.12, 2), 20);
                    if (Math.abs((node.currentTime || 0) - target) > 1) {
                        try {
                            node.currentTime = target;
                            await eventOrDelay('seeked', 2400);
                        } catch (_error) {}
                    }
                }
                await delay(450);
                if (node.readyState < 2 || !node.videoWidth || !node.videoHeight) {
                    return '';
                }
                const width = Math.min(node.videoWidth, 1280);
                const height = Math.max(
                    1, Math.round(width * node.videoHeight / node.videoWidth)
                );
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const context = canvas.getContext('2d', {alpha: false});
                if (!context) return '';
                try {
                    context.drawImage(node, 0, 0, width, height);
                    return canvas.toDataURL('image/jpeg', 0.82);
                } catch (_error) {
                    return '';
                }
            }
            """
        )
    except Exception:
        encoded = ""
    image_bytes = b""
    if isinstance(encoded, str) and encoded.startswith("data:image/jpeg;base64,"):
        try:
            image_bytes = _normalize_raster_to_jpeg(
                base64.b64decode(encoded.split(",", 1)[1], validate=True),
                quality=84,
            )
        except (TypeError, ValueError):
            image_bytes = b""
    if not image_bytes:
        image_bytes = _capture_locator_jpeg(page, video, quality=82)
    return image_bytes if _meaningful_raster_evidence(image_bytes) else b""


def _wait_for_xiaohongshu_media(page):
    """Give the opened note a bounded chance to replace lazy placeholders."""

    try:
        page.wait_for_function(
            r"""
            () => {
                const root = document.querySelector(
                    '.note-content, [class*="note-content"], ' +
                    '[class*="note-detail"], [class*="detail-content"]'
                );
                if (!root) return false;
                const readyImage = Array.from(root.querySelectorAll('img')).some(
                    (node) => node.complete && node.naturalWidth >= 480 &&
                        node.naturalHeight >= 270
                );
                const readyVideo = Array.from(root.querySelectorAll('video')).some(
                    (node) => node.readyState >= 2 && node.videoWidth >= 320 &&
                        node.videoHeight >= 180
                );
                return readyImage || readyVideo;
            }
            """,
            timeout=3500,
        )
    except Exception:
        pass


def _xiaohongshu_video_locator(page):
    selectors = (
        '.note-content video',
        '[class*="note-content"] video',
        '[class*="note-slider"] video',
        '[class*="carousel"] video',
        '[class*="note-detail"] video',
        '[class*="detail-content"] video',
        '[class*="video-container"] video',
    )
    for selector in selectors:
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 8)):
                locator = locators.nth(index)
                if not _media_is_post_content(locator):
                    continue
                box = locator.bounding_box()
                if not isinstance(box, dict):
                    continue
                if float(box.get("width") or 0) < 240 or float(
                    box.get("height") or 0
                ) < 180:
                    continue
                return locator
        except Exception:
            continue
    return None


def _capture_xiaohongshu_video_frames(page, maximum=2):
    """Capture representative frames from the current opened Rednote video."""

    video = _xiaohongshu_video_locator(page)
    if video is None:
        return []
    try:
        maximum = min(max(int(maximum or 1), 1), 3)
    except (TypeError, ValueError):
        maximum = 2
    fractions = (0.12, 0.52, 0.84)[:maximum]
    frames = []
    known_hashes = []
    for fraction in fractions:
        try:
            ready = video.evaluate(
                r"""
                async (node, fraction) => {
                    const delay = (ms) => new Promise(
                        (resolve) => setTimeout(resolve, ms)
                    );
                    const eventOrDelay = (name, ms) => Promise.race([
                        new Promise((resolve) => node.addEventListener(
                            name, resolve, {once: true}
                        )),
                        delay(ms),
                    ]);
                    node.muted = true;
                    node.volume = 0;
                    node.playsInline = true;
                    if (node.readyState < 2) {
                        await eventOrDelay('loadeddata', 2400);
                    }
                    try { await node.play(); } catch (_error) {}
                    if (Number.isFinite(node.duration) && node.duration > 1) {
                        const target = Math.min(
                            Math.max(node.duration * fraction, 0.35),
                            Math.max(node.duration - 0.2, 0.35)
                        );
                        try {
                            node.currentTime = target;
                            await eventOrDelay('seeked', 2200);
                        } catch (_error) {}
                    }
                    await delay(350);
                    try { node.pause(); } catch (_error) {}
                    return Boolean(
                        node.readyState >= 2 && node.videoWidth && node.videoHeight
                    );
                }
                """,
                fraction,
            )
        except Exception:
            ready = False
        if not ready:
            continue
        image_bytes = _capture_locator_jpeg(page, video, quality=84)
        image_bytes = _normalize_raster_to_jpeg(image_bytes, quality=86)
        if not _detailed_raster_evidence(image_bytes):
            continue
        if not _raster_is_distinct(image_bytes, known_hashes, maximum_distance=6):
            continue
        frames.append(image_bytes)
    return frames


def _xiaohongshu_post_media(page):
    """Return the first three distinct, highest-quality note images."""

    selector = ", ".join(
        (
            '.swiper-slide:not(.swiper-slide-duplicate) img',
            '[class*="note-slider"] img',
            '[class*="carousel"] img',
            '[class*="note-detail"] img',
            '[class*="detail-content"] img',
        )
    )
    output = []
    seen_sources = set()
    try:
        locators = page.locator(selector)
        count = min(int(locators.count()), 80)
    except Exception:
        return output
    for index in range(count):
        locator = locators.nth(index)
        if not _media_is_post_content(locator):
            continue
        try:
            payload = locator.evaluate(
                r"""
                (node) => {
                    const rect = node.getBoundingClientRect();
                    const sources = [];
                    const add = (value) => {
                        value = (value || '').trim();
                        if (value && !sources.includes(value)) sources.push(value);
                    };
                    const srcset = (node.getAttribute('srcset') || '')
                        .split(',').map((part) => part.trim()).filter(Boolean)
                        .map((part) => {
                            const bits = part.split(/\s+/);
                            const descriptor = bits[1] || '0w';
                            const score = parseFloat(descriptor) || 0;
                            return {url: bits[0] || '', score};
                        }).sort((left, right) => right.score - left.score);
                    for (const item of srcset) add(item.url);
                    add(node.getAttribute('data-src'));
                    add(node.getAttribute('data-original'));
                    add(node.currentSrc);
                    add(node.src);
                    return {
                        sources,
                        width: node.naturalWidth || rect.width || 0,
                        height: node.naturalHeight || rect.height || 0,
                    };
                }
                """
            )
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        sources = [
            str(value or "").strip()
            for value in payload.get("sources", [])
            if str(value or "").strip()
        ] if isinstance(payload.get("sources"), list) else []
        source = next(
            (value for value in sources if value.lower().startswith("https://")),
            "",
        )
        try:
            width = float(payload.get("width") or 0)
            height = float(payload.get("height") or 0)
        except (TypeError, ValueError):
            continue
        source_key = source.split("?", 1)[0].casefold()
        if (
            not source_key
            or source_key in seen_sources
            or width < 240
            or height < 180
            or re.search(r"avatar|emoji|logo|icon|sprite", source_key)
        ):
            continue
        seen_sources.add(source_key)
        output.append((locator, source))
        if len(output) >= 3:
            break
    return output


def _capture_social_post_assets(page, platform, fallback_image_url=""):
    """Capture the platform-specific evidence package shown in chat."""

    assets = []
    if platform == "bilibili":
        known_hashes = []
        for cover_url in _bilibili_cover_urls(page, fallback_image_url):
            image_bytes = _download_post_image_jpeg(page, cover_url)
            if not _meaningful_raster_evidence(image_bytes):
                continue
            if not _raster_is_distinct(image_bytes, known_hashes):
                continue
            assets.append(
                {
                    "kind": "video_cover",
                    "label": "视频封面",
                    "image_bytes": image_bytes,
                }
            )
            break
        frame_bytes = _capture_bilibili_video_frame(page)
        if (
            _meaningful_raster_evidence(frame_bytes)
            and _raster_is_distinct(frame_bytes, known_hashes)
        ):
            assets.append(
                {
                    "kind": "video_frame",
                    "label": "视频帧 1",
                    "image_bytes": frame_bytes,
                }
            )
        print(
            "[SOCIAL BILIBILI VISUAL ASSETS]",
            "cover=" + str(sum(item["kind"] == "video_cover" for item in assets)),
            "frames=" + str(sum(item["kind"] == "video_frame" for item in assets)),
        )
        # Never append the video page/container screenshot. It is dominated by
        # navigation, recommendations and unloaded-player chrome.
        return assets[:2]

    if platform == "youtube":
        metadata = _youtube_video_metadata(page)
        known_hashes = []
        for cover_url in _youtube_cover_urls(
            page, fallback_image_url, metadata=metadata
        ):
            image_bytes = _download_post_image_jpeg(page, cover_url)
            if not _meaningful_raster_evidence(image_bytes):
                continue
            if not _raster_is_distinct(image_bytes, known_hashes):
                continue
            assets.append(
                {
                    "kind": "video_cover",
                    "label": "视频封面",
                    "image_bytes": image_bytes,
                }
            )
            break
        frame_bytes = _capture_youtube_video_frame(page)
        if (
            _meaningful_raster_evidence(frame_bytes)
            and _raster_is_distinct(frame_bytes, known_hashes)
        ):
            assets.append(
                {
                    "kind": "video_frame",
                    "label": "视频帧 1",
                    "image_bytes": frame_bytes,
                }
            )
        print(
            "[SOCIAL YOUTUBE VISUAL ASSETS]",
            "cover=" + str(sum(item["kind"] == "video_cover" for item in assets)),
            "frames=" + str(sum(item["kind"] == "video_frame" for item in assets)),
            "short=" + str(bool(metadata.get("is_short"))).lower(),
        )
        # Never capture the full watch/Shorts page. Its recommendations,
        # comments, navigation and player chrome are not current-video proof.
        return assets[:2]

    if platform == "xiaohongshu":
        _wait_for_xiaohongshu_media(page)
        known_hashes = []
        for index, image_bytes in enumerate(
            _capture_xiaohongshu_video_frames(page, maximum=2), start=1
        ):
            if not _raster_is_distinct(
                image_bytes, known_hashes, maximum_distance=6
            ):
                continue
            assets.append(
                {
                    "kind": "video_frame",
                    "label": "视频帧 " + str(index),
                    "image_bytes": image_bytes,
                }
            )
        for index, (locator, image_url) in enumerate(
            _xiaohongshu_post_media(page), start=1
        ):
            image_bytes = _download_post_image_jpeg(page, image_url)
            if not image_bytes:
                image_bytes = _capture_locator_jpeg(page, locator, quality=82)
            image_bytes = _normalize_raster_to_jpeg(image_bytes, quality=86)
            if not _detailed_raster_evidence(image_bytes):
                print(
                    "[SOCIAL XIAOHONGSHU MEDIA REJECTED]",
                    "reason=blur_or_placeholder",
                    "image=" + str(index),
                )
                continue
            if not _raster_is_distinct(
                image_bytes, known_hashes, maximum_distance=6
            ):
                continue
            if image_bytes:
                assets.append(
                    {
                        "kind": "media",
                        "label": "图 " + str(index),
                        "image_bytes": image_bytes,
                    }
                )
        text_container = _first_post_text_container(page, platform)
        if text_container is not None:
            image_bytes = _capture_locator_jpeg(
                page, text_container, quality=74, timeout_ms=6500
            )
            if image_bytes:
                assets.append(
                    {
                        "kind": "text",
                        "label": "正文",
                        "image_bytes": image_bytes,
                    }
                )
        if not assets:
            for index, frame in enumerate(
                _capture_post_visual_frames(
                    page, maximum=2, platform=platform
                ),
                start=1,
            ):
                try:
                    image_bytes = base64.b64decode(frame, validate=True)
                except (TypeError, ValueError):
                    continue
                if (
                    image_bytes.startswith(b"\xff\xd8\xff")
                    and not _detailed_raster_evidence(image_bytes)
                ):
                    continue
                assets.append(
                    {
                        "kind": "media" if index == 1 else "text",
                        "label": "图片" if index == 1 else "正文",
                        "image_bytes": image_bytes,
                    }
                )
        print(
            "[SOCIAL XIAOHONGSHU VISUAL ASSETS]",
            "images=" + str(sum(item["kind"] == "media" for item in assets)),
            "frames=" + str(
                sum(item["kind"] == "video_frame" for item in assets)
            ),
            "text=" + str(sum(item["kind"] == "text" for item in assets)),
        )
        return assets[:4]

    if platform == "reddit":
        text_container = _first_post_text_container(page, platform)
        if text_container is None:
            return []
        image_bytes = _capture_locator_jpeg(
            page, text_container, quality=74, timeout_ms=6500
        )
        return (
            [{"kind": "text", "label": "帖子正文", "image_bytes": image_bytes}]
            if image_bytes else []
        )

    frames = _capture_post_visual_frames(page, maximum=2, platform=platform)
    for index, frame in enumerate(frames, start=1):
        try:
            image_bytes = base64.b64decode(frame, validate=True)
        except (TypeError, ValueError):
            continue
        assets.append(
            {
                "kind": "media" if index == 1 else "text",
                "label": "图片" if index == 1 else "正文",
                "image_bytes": image_bytes,
            }
        )
    return assets


def _plain_bilibili_text(value, limit=600):
    """Remove only Bilibili's search-highlight markup from literal text."""

    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]{0,240}>", " ", text)
    return " ".join(text.split())[: max(int(limit or 0), 0)]


def _extract_bilibili_search_response_candidates(payload):
    """Read bounded video rows from Bilibili's own search-page response."""

    if not isinstance(payload, dict):
        return []
    try:
        if int(payload.get("code", 0)) != 0:
            return []
    except (TypeError, ValueError):
        return []
    root = payload.get("data")
    if not isinstance(root, (dict, list)):
        return []

    queue = [root]
    inspected = 0
    records = []
    while queue and inspected < 2400:
        current = queue.pop(0)
        inspected += 1
        if isinstance(current, list):
            queue.extend(current[:400])
            continue
        if not isinstance(current, dict):
            continue
        bvid = str(current.get("bvid") or "").strip()
        raw_url = str(
            current.get("arcurl") or current.get("url") or ""
        ).strip()
        if raw_url.startswith("http://"):
            raw_url = "https://" + raw_url[len("http://"):]
        if re.fullmatch(r"BV[0-9A-Za-z]{10,14}", bvid):
            raw_url = raw_url or (
                "https://www.bilibili.com/video/" + bvid
            )
        url = _allowed_social_url("bilibili", raw_url)
        title = _plain_bilibili_text(
            current.get("title") or current.get("name"), 300
        )
        if url and title:
            records.append(current)
        for key in ("result", "data", "items", "list"):
            child = current.get(key)
            if isinstance(child, (dict, list)):
                queue.append(child)

    candidates = []
    seen_urls = set()
    for record in records:
        bvid = str(record.get("bvid") or "").strip()
        raw_url = str(
            record.get("arcurl") or record.get("url") or ""
        ).strip()
        if raw_url.startswith("http://"):
            raw_url = "https://" + raw_url[len("http://"):]
        if not raw_url and re.fullmatch(r"BV[0-9A-Za-z]{10,14}", bvid):
            raw_url = "https://www.bilibili.com/video/" + bvid
        url = _allowed_social_url("bilibili", raw_url)
        if not url or url in seen_urls:
            continue
        title = _plain_bilibili_text(
            record.get("title") or record.get("name"), 300
        )
        if not title:
            continue
        author = _plain_bilibili_text(
            record.get("author") or record.get("up_name")
            or record.get("uname"), 160
        )
        description = _plain_bilibili_text(
            record.get("description") or record.get("desc"), 360
        )
        published_at = ""
        try:
            timestamp = int(
                record.get("pubdate") or record.get("senddate")
                or record.get("created") or 0
            )
            if timestamp > 0:
                published_at = time.strftime(
                    "%Y-%m-%d", time.localtime(timestamp)
                )
        except (TypeError, ValueError, OSError, OverflowError):
            published_at = ""
        play = _plain_bilibili_text(record.get("play"), 80)
        duration = _plain_bilibili_text(record.get("duration"), 40)
        text_parts = [title]
        if author:
            text_parts.append("UP主：" + author)
        if published_at:
            text_parts.append("发布时间：" + published_at)
        if play and play not in {"--", "-"}:
            text_parts.append("播放：" + play)
        if duration:
            text_parts.append("时长：" + duration)
        if description:
            text_parts.append(description)
        image_url = _normalize_social_image_url(
            "bilibili",
            record.get("pic") or record.get("cover")
            or record.get("image_url"),
        )
        candidates.append(
            {
                "platform": "bilibili",
                "url": url,
                "title": title,
                "description": description,
                "author": author,
                "published": published_at,
                "visible_text": " ".join(text_parts)[:1400],
                "image_url": image_url,
                "image_alt": title,
                "source_kind": "network_result",
            }
        )
        seen_urls.add(url)
        if len(candidates) >= MAX_POST_CANDIDATES:
            break
    return candidates


def _is_bilibili_search_api_response(value):
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").lower()
    return (
        hostname == "api.bilibili.com"
        and "/search/" in str(parsed.path or "").lower()
    )


def _store_bilibili_search_response(cache_key, response):
    """Capture one successful native search response while its page loads."""

    if not cache_key or not _is_bilibili_search_api_response(
        getattr(response, "url", "")
    ):
        return
    try:
        if int(getattr(response, "status", 0) or 0) != 200:
            return
        payload = response.json()
        try:
            response_code = int(payload.get("code", 0))
        except (AttributeError, TypeError, ValueError):
            response_code = -1
        if response_code != 0:
            print(
                "[SOCIAL BILIBILI RESPONSE REJECTED]",
                "code=" + str(response_code),
            )
            return
        candidates = _extract_bilibili_search_response_candidates(
            payload
        )
    except Exception as error:
        print("[SOCIAL BILIBILI RESPONSE ERROR]", repr(error))
        return
    if not candidates:
        return
    existing = _BILIBILI_SEARCH_RESPONSE_CANDIDATES.setdefault(cache_key, [])
    known_urls = {
        str(item.get("url") or "")
        for item in existing if isinstance(item, dict)
    }
    for candidate in candidates:
        if candidate["url"] in known_urls:
            continue
        existing.append(candidate)
        known_urls.add(candidate["url"])
        if len(existing) >= MAX_POST_CANDIDATES:
            break
    print(
        "[SOCIAL BILIBILI RESPONSE]",
        "candidates=" + str(len(existing)),
    )


def _extract_post_candidates(page, platform):
    """Collect visible post links and their real image URLs from the result grid."""

    extraction_script = r"""
            () => {
                const output = new Map();
                const roots = [document];
                let inspectedRootNodes = 0;
                for (let index = 0; index < roots.length && index < 32; index++) {
                    const root = roots[index];
                    if (!root || !root.querySelectorAll) continue;
                    for (const node of root.querySelectorAll('*')) {
                        inspectedRootNodes += 1;
                        if (inspectedRootNodes > 6000) break;
                        if (node.shadowRoot && roots.length < 32) {
                            roots.push(node.shadowRoot);
                        }
                    }
                    if (inspectedRootNodes > 6000) break;
                }
                const queryAll = (selector) => {
                    const seen = new Set();
                    const items = [];
                    for (const root of roots) {
                        if (!root || !root.querySelectorAll) continue;
                        for (const item of root.querySelectorAll(selector)) {
                            if (seen.has(item)) continue;
                            seen.add(item);
                            items.push(item);
                        }
                    }
                    return items;
                };
                const cardSelector = [
                    '.bili-video-card',
                    '.video-list-item',
                    '.search-all-list-item',
                    'ytd-video-renderer',
                    'ytd-grid-video-renderer',
                    'ytd-rich-item-renderer',
                    'ytd-reel-item-renderer',
                    'ytm-shorts-lockup-view-model-v2',
                    'ytd-rich-grid-media',
                    'yt-lockup-view-model',
                    '.media-card',
                    '.note-item',
                    '.feed-card',
                    '[class*="note-item"]',
                    '[class*="feed-card"]',
                    '[class*="search-result"]',
                    'shreddit-post',
                    'article',
                    '[class*="bili-video-card"]',
                    '[class*="video-list-item"]',
                    '[class*="search-card"]'
                ].join(', ');
                const addAnchor = (anchor, sourceKind) => {
                    if (!anchor) return;
                    const href = anchor.href || '';
                    if (!href) return;
                    const matchedCard = anchor.closest(cardSelector);
                    let container = matchedCard || anchor;
                    let inferredCard = false;
                    let fallbackContainer = null;
                    if (!matchedCard) {
                        for (let depth = 0; depth < 6 && container.parentElement; depth++) {
                            const parent = container.parentElement;
                            const parentText = (parent.innerText || '').trim();
                            container = parent;
                            if (
                                !fallbackContainer && parentText.length >= 8 &&
                                parentText.length <= 1400
                            ) {
                                fallbackContainer = parent;
                            }
                            const parentImage = parent.querySelector &&
                                parent.querySelector('img');
                            if (
                                parentImage && parentText.length >= 8 &&
                                parentText.length <= 600
                            ) {
                                inferredCard = true;
                                break;
                            }
                        }
                        if (!inferredCard && fallbackContainer) {
                            container = fallbackContainer;
                        }
                    }
                    const image = anchor.querySelector('img') ||
                        (container.querySelector && container.querySelector('img'));
                    const titleNode = container.querySelector && container.querySelector(
                        '.bili-video-card__info--tit, ' +
                        '[class*="video-card__info--tit"], a#video-title, ' +
                        '#video-title[title], h3[title], [aria-label][href*="/shorts/"]'
                    );
                    const title = titleNode ? (
                        titleNode.getAttribute('title') ||
                        titleNode.getAttribute('aria-label') ||
                        titleNode.innerText || ''
                    ).trim() : '';
                    const containerText = (container.innerText || anchor.innerText || '')
                        .replace(/\s+/g, ' ').trim();
                    const anchorLabel = (
                        anchor.getAttribute('title') ||
                        anchor.getAttribute('aria-label') || ''
                    ).replace(/\s+/g, ' ').trim();
                    const text = [title, containerText, anchorLabel]
                        .filter(Boolean).filter((value, index, values) =>
                            values.indexOf(value) === index
                        ).join(' ').trim();
                    if (!text) return;
                    const imageCandidates = image ? [
                        image.currentSrc,
                        image.src,
                        image.getAttribute('data-src'),
                        image.getAttribute('data-thumb'),
                        (image.getAttribute('srcset') || '').split(',')
                            .map((part) => part.trim().split(/\s+/)[0] || '')
                            .filter(Boolean).slice(-1)[0] || ''
                    ].filter(Boolean) : [];
                    const imageUrl = imageCandidates.find((value) =>
                        /^https?:\/\//i.test(value) || value.startsWith('//')
                    ) || '';
                    const normalizedKind = (
                        Boolean(matchedCard) || inferredCard ||
                        sourceKind === 'result_card'
                    ) ? 'result_card' : 'generic_link';
                    const item = {
                        url: href,
                        visible_text: text.slice(0, 1400),
                        image_url: imageUrl,
                        image_alt: image ? (image.alt || '').slice(0, 240) : '',
                        source_kind: normalizedKind,
                        // Keep DOM evidence separate from the broad URL pass.
                        // A site footer may contain a /video/ link, but that
                        // alone never proves it is a rendered search card.
                        dom_card_matched: Boolean(matchedCard) || inferredCard,
                    };
                    const previous = output.get(href);
                    if (!previous) {
                        output.set(href, item);
                        return;
                    }
                    if (item.visible_text.length > previous.visible_text.length) {
                        previous.visible_text = item.visible_text;
                    }
                    if (!previous.image_url && item.image_url) {
                        previous.image_url = item.image_url;
                        previous.image_alt = item.image_alt;
                    }
                    if (normalizedKind === 'result_card') {
                        previous.source_kind = normalizedKind;
                    }
                    if (item.dom_card_matched) {
                        previous.dom_card_matched = true;
                    }
                };

                // Search-result video links are selected first. Hidden site menus can
                // contain hundreds of anchors before the visible result list.
                for (const anchor of queryAll(
                    'a[href*="/video/"], a[href*="/bangumi/play/"], ' +
                    'a[href*="youtube.com/watch?v="], a[href^="/watch?v="], ' +
                    'a[href*="/shorts/"], a[href*="/live/"], ' +
                    'a[href*="/explore/"], a[href*="/discovery/item/"], ' +
                    'a[href*="/comments/"], a[href*="/status/"], ' +
                    'a[href*="/p/"], a[href*="/reel/"]'
                )) {
                    addAnchor(anchor, 'result_card');
                }
                let inspected = 0;
                for (const anchor of queryAll('a[href]')) {
                    inspected += 1;
                    if (inspected > 2000) break;
                    addAnchor(anchor, 'generic_link');
                }
                return Array.from(output.values()).slice(0, 400);
            }
            """
    surfaces = getattr(page, "frames", None)
    if not isinstance(surfaces, list) or not surfaces:
        surfaces = [page]
    raw_items = []
    successful_surface = False
    for surface in surfaces[:12]:
        try:
            evaluated = surface.evaluate(extraction_script)
            if isinstance(evaluated, list):
                raw_items.extend(evaluated)
            successful_surface = True
        except Exception as error:
            print("[SOCIAL POST CANDIDATE ERROR]", repr(error))
    if not successful_surface:
        return []
    candidates_by_url = {}
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        url = _allowed_social_url(platform, item.get("url"))
        visible_text = str(item.get("visible_text") or "").strip()[:1400]
        image_url = _normalize_social_image_url(
            platform, item.get("image_url")
        )
        if not url or not visible_text:
            continue
        if (
            platform in ("instagram", "xiaohongshu")
            and not image_url
            and str(item.get("source_kind") or "") != "result_card"
        ):
            continue
        candidate = {
            "platform": platform,
            "url": url,
            "visible_text": visible_text,
            "image_url": image_url,
            "image_alt": str(item.get("image_alt") or "").strip()[:240],
            "source_kind": str(
                item.get("source_kind") or "generic_link"
            ).strip()[:40],
            "dom_card_matched": bool(item.get("dom_card_matched")),
            "dom_card_signal_present": "dom_card_matched" in item,
        }
        previous = candidates_by_url.get(url)
        if previous is None:
            candidates_by_url[url] = candidate
            continue
        if len(candidate["visible_text"]) > len(previous["visible_text"]):
            previous["visible_text"] = candidate["visible_text"]
        if not previous["image_url"] and candidate["image_url"]:
            previous["image_url"] = candidate["image_url"]
            previous["image_alt"] = candidate["image_alt"]
        if candidate["source_kind"] == "result_card":
            previous["source_kind"] = "result_card"
        if candidate["dom_card_matched"]:
            previous["dom_card_matched"] = True
        if candidate["dom_card_signal_present"]:
            previous["dom_card_signal_present"] = True
    candidates = list(candidates_by_url.values())
    if platform == "bilibili":
        result_cards = [
            item for item in candidates
            if (
                (
                    (
                        item.get("dom_card_matched")
                        and bool(item.get("image_url"))
                    )
                    or (
                        not item.get("dom_card_signal_present")
                        and (
                            item.get("source_kind") == "result_card"
                            or bool(item.get("image_url"))
                        )
                    )
                )
                and any(
                    marker in str(item.get("url") or "").lower()
                    for marker in ("/video/", "/bangumi/play/")
                )
                and 4 <= len(str(item.get("visible_text") or "")) <= 600
                and not any(
                    marker in str(item.get("visible_text") or "").casefold()
                    for marker in (
                        "协议汇总", "侵权申诉", "帮助中心", "社区中心",
                        "广告合作", "名人堂", "mcn管理中心", "高级弹幕",
                    )
                )
            )
        ]
        for item in result_cards:
            item["source_kind"] = "result_card"
        # A raw /video/ URL in site chrome is not search evidence. Bilibili's
        # compatibility page contains one such legacy link, which previously
        # became a false result when the real grid did not render.
        candidates = result_cards
    elif platform == "youtube":
        result_cards = [
            item for item in candidates
            if (
                (
                    item.get("dom_card_matched")
                    if item.get("dom_card_signal_present")
                    else item.get("source_kind") == "result_card"
                )
                and bool(_canonical_youtube_video_url(item.get("url")))
                and 4 <= len(str(item.get("visible_text") or "")) <= 900
            )
        ]
        for item in result_cards:
            item["source_kind"] = "result_card"
        # A watch link in navigation/history is not a rendered search result.
        # Only recognized YouTube video/Shorts card containers survive.
        candidates = result_cards
    return candidates[:MAX_POST_CANDIDATES]


def _social_dom_diagnostics(page):
    """Return bounded structural counts for diagnosing rendered social pages."""

    script = r"""
        () => {
            const roots = [document];
            let inspected = 0;
            for (let index = 0; index < roots.length && index < 32; index++) {
                const root = roots[index];
                if (!root || !root.querySelectorAll) continue;
                for (const node of root.querySelectorAll('*')) {
                    inspected += 1;
                    if (inspected > 6000) break;
                    if (node.shadowRoot && roots.length < 32) {
                        roots.push(node.shadowRoot);
                    }
                }
                if (inspected > 6000) break;
            }
            const count = (selector) => roots.reduce(
                (total, root) => total + (
                    root && root.querySelectorAll
                        ? root.querySelectorAll(selector).length : 0
                ), 0
            );
            return {
                anchors: count('a[href]'),
                video_links: count(
                    'a[href*="/video/"], a[href*="/bangumi/play/"], ' +
                    'a[href*="/watch?v="], a[href*="/shorts/"], ' +
                    'a[href*="/live/"]'
                ),
                video_cards: count(
                    '.bili-video-card, .video-list-item, .search-all-list-item, ' +
                    '.media-card, [class*="bili-video-card"], ' +
                    '[class*="video-list-item"], ytd-video-renderer, ' +
                    'ytd-grid-video-renderer, ytd-rich-item-renderer, ' +
                    'ytd-reel-item-renderer, ytm-shorts-lockup-view-model-v2, ' +
                    'ytd-rich-grid-media, yt-lockup-view-model'
                ),
            };
        }
    """
    surfaces = getattr(page, "frames", None)
    if not isinstance(surfaces, list) or not surfaces:
        surfaces = [page]
    totals = {
        "frames": len(surfaces[:12]),
        "anchors": 0,
        "video_links": 0,
        "video_cards": 0,
    }
    for surface in surfaces[:12]:
        try:
            values = surface.evaluate(script)
        except Exception:
            continue
        if not isinstance(values, dict):
            continue
        for key in ("anchors", "video_links", "video_cards"):
            try:
                totals[key] += max(int(values.get(key) or 0), 0)
            except (TypeError, ValueError):
                pass
    return totals


def _compose_social_visible_text(snapshots, post_candidates, limit=18000):
    """Put bounded visible result-card text before generic page chrome."""

    seen_lines = set()
    result_lines = []
    for candidate in post_candidates if isinstance(post_candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        text = " ".join(
            str(candidate.get("visible_text") or "").split()
        ).strip()
        if not text:
            continue
        line = "VISIBLE RESULT CARD: " + text[:1400]
        if line in seen_lines:
            continue
        seen_lines.add(line)
        result_lines.append(line)
    for snapshot in snapshots if isinstance(snapshots, list) else []:
        for line in str(snapshot or "").splitlines():
            clean_line = line.strip()
            if clean_line and clean_line not in seen_lines:
                seen_lines.add(clean_line)
                result_lines.append(clean_line)
    return "\n".join(result_lines)[: max(int(limit or 0), 0)]


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
                    const images = current.querySelectorAll
                        ? Array.from(current.querySelectorAll('img')).filter((item) => {
                            const source = (
                                item.currentSrc || item.src || item.alt || ''
                            ).toLowerCase();
                            const rect = item.getBoundingClientRect();
                            return rect.width >= 80 && rect.height >= 60 &&
                                !/avatar|emoji|logo|icon|sprite/.test(source);
                        }).sort((left, right) => {
                            const a = left.getBoundingClientRect();
                            const b = right.getBoundingClientRect();
                            return (b.width * b.height) - (a.width * a.height);
                        }) : [];
                    const image = images[0] || null;
                    const closestLink = current.closest && current.closest('a[href]');
                    const childLink = current.querySelector && current.querySelector('a[href]');
                    const link = closestLink || childLink;
                    if (text && !fallback) {
                        const rect = current.getBoundingClientRect();
                        fallback = {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image ? (
                                image.currentSrc || image.src ||
                                image.getAttribute('data-src') || ''
                            ) : '',
                            clip: {
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height,
                            },
                        };
                    }
                    if (text && image && text.length <= 2400) {
                        const rect = current.getBoundingClientRect();
                        return {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image.currentSrc || image.src ||
                                image.getAttribute('data-src') || '',
                            clip: {
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height,
                            },
                        };
                    }
                    current = current.parentElement;
                }
                return fallback || {
                    visible_text: '', url: '', image_url: '', clip: null
                };
            }
            """
        )
    except Exception as error:
        print("[SOCIAL TITLE CARD ERROR]", repr(error))
        return {}
    return raw if isinstance(raw, dict) else {}


def _fresh_social_title_card_data(page, title):
    """Read a title card from the current DOM without retaining a stale node."""

    try:
        raw = page.evaluate(
            r"""
            (rawTitle) => {
                const normalize = (value) => (value || '')
                    .replace(/\s+/g, ' ').trim().toLocaleLowerCase();
                const wanted = normalize(rawTitle);
                if (!wanted) return null;
                const nodes = Array.from(document.querySelectorAll(
                    'a[href], [role="link"], [class*="note-item"], ' +
                    '[class*="feed-card"], [class*="search-item"], ' +
                    'ytd-video-renderer, ytd-grid-video-renderer, ' +
                    'ytd-reel-item-renderer, ytm-shorts-lockup-view-model-v2, ' +
                    'ytd-rich-grid-media, yt-lockup-view-model, ' +
                    'h1, h2, h3, span, div'
                ));
                let best = null;
                let bestScore = -1;
                for (const node of nodes) {
                    const text = normalize(node.innerText || node.textContent);
                    const usefulFragment = wanted.includes(text) &&
                        text.length >= Math.max(6, Math.ceil(wanted.length * 0.55));
                    if (!text || (!text.includes(wanted) && !usefulFragment)) {
                        continue;
                    }
                    const rect = node.getBoundingClientRect();
                    if (rect.width < 2 || rect.height < 2) continue;
                    let score = text === wanted ? 1000 : 500;
                    score -= Math.min(Math.abs(text.length - wanted.length), 300);
                    if (score > bestScore) {
                        best = node;
                        bestScore = score;
                    }
                }
                if (!best) return null;
                let current = best;
                let fallback = null;
                for (let depth = 0; current && depth < 10; depth++) {
                    const text = (current.innerText || current.textContent || '')
                        .replace(/\s+/g, ' ').trim();
                    const images = current.querySelectorAll
                        ? Array.from(current.querySelectorAll('img')).filter((item) => {
                            const source = (
                                item.currentSrc || item.src || item.alt || ''
                            ).toLowerCase();
                            const rect = item.getBoundingClientRect();
                            return rect.width >= 80 && rect.height >= 60 &&
                                !/avatar|emoji|logo|icon|sprite/.test(source);
                        }).sort((left, right) => {
                            const a = left.getBoundingClientRect();
                            const b = right.getBoundingClientRect();
                            return (b.width * b.height) - (a.width * a.height);
                        }) : [];
                    const image = images[0] || null;
                    const closestLink = current.closest && current.closest('a[href]');
                    const childLink = current.querySelector && current.querySelector('a[href]');
                    const link = closestLink || childLink;
                    if (text && !fallback) {
                        const rect = current.getBoundingClientRect();
                        fallback = {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image ? (
                                image.currentSrc || image.src ||
                                image.getAttribute('data-src') || ''
                            ) : '',
                            clip: {
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height,
                            },
                        };
                    }
                    if (text && image && text.length <= 2400) {
                        const rect = current.getBoundingClientRect();
                        return {
                            visible_text: text.slice(0, 1400),
                            url: link ? (link.href || '') : '',
                            image_url: image.currentSrc || image.src ||
                                image.getAttribute('data-src') || '',
                            clip: {
                                x: rect.left + window.scrollX,
                                y: rect.top + window.scrollY,
                                width: rect.width,
                                height: rect.height,
                            },
                        };
                    }
                    current = current.parentElement;
                }
                return fallback;
            }
            """,
            title,
        )
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _click_fresh_social_title_node(page, title):
    """Atomically re-find and click a title after a reactive DOM replacement."""

    try:
        return bool(
            page.evaluate(
                r"""
                (rawTitle) => {
                    const normalize = (value) => (value || '')
                        .replace(/\s+/g, ' ').trim().toLocaleLowerCase();
                    const wanted = normalize(rawTitle);
                    if (!wanted) return false;
                    const nodes = Array.from(document.querySelectorAll(
                        'a[href], [role="link"], [class*="note-item"], ' +
                        '[class*="feed-card"], [class*="search-item"], ' +
                        'ytd-video-renderer, ytd-grid-video-renderer, ' +
                        'ytd-reel-item-renderer, ' +
                        'ytm-shorts-lockup-view-model-v2, ytd-rich-grid-media, ' +
                        'yt-lockup-view-model, ' +
                        'h1, h2, h3, span, div'
                    ));
                    let best = null;
                    let bestScore = -1;
                    for (const node of nodes) {
                        const text = normalize(node.innerText || node.textContent);
                        const usefulFragment = wanted.includes(text) &&
                            text.length >= Math.max(
                                6, Math.ceil(wanted.length * 0.55)
                            );
                        if (!text || (!text.includes(wanted) && !usefulFragment)) {
                            continue;
                        }
                        const rect = node.getBoundingClientRect();
                        if (rect.width < 2 || rect.height < 2) continue;
                        let score = text === wanted ? 1000 : 500;
                        score -= Math.min(text.length - wanted.length, 300);
                        if (score > bestScore) {
                            best = node;
                            bestScore = score;
                        }
                    }
                    if (!best) return false;
                    const clickable = best.closest(
                        'a[href], button, [role="link"], ' +
                        '[class*="note-item"], [class*="feed-card"], ' +
                        '[class*="search-item"], ytd-video-renderer, ' +
                        'ytd-grid-video-renderer, ytd-reel-item-renderer, ' +
                        'ytm-shorts-lockup-view-model-v2, ytd-rich-grid-media, ' +
                        'yt-lockup-view-model'
                    ) || best;
                    clickable.click();
                    return true;
                }
                """,
                title,
            )
        )
    except Exception:
        return False


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
        page_context = getattr(page, "context", None)
        if page_context is not None:
            managed_browser.keep_page_background(page_context, page)
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
                        locator = None
                        card_data = _fresh_social_title_card_data(page, title)
                        if not card_data:
                            continue
                    else:
                        locator = locator.first
                        card_data = _title_card_data(locator)
                        if not card_data:
                            card_data = _fresh_social_title_card_data(page, title)
                    visible_text = str(
                        card_data.get("visible_text") or title
                    ).strip()[:1400]
                    image_url = _normalize_social_image_url(
                        platform, card_data.get("image_url")
                    )
                    direct_card_url = _allowed_social_url(
                        platform, card_data.get("url")
                    )
                    # A plain search suggestion can exactly repeat a model-
                    # selected title but has neither post URL nor result image.
                    # Do not click or screenshot such text as post evidence.
                    if not direct_card_url and not image_url:
                        continue
                    if platform == "xiaohongshu":
                        # Capture the media raster itself. A whole-card crop can
                        # look sharp because of the author/date text while its
                        # actual thumbnail remains deliberately blurred.
                        search_card_bytes = _download_post_image_jpeg(
                            page, image_url
                        )
                        if not _detailed_raster_evidence(search_card_bytes):
                            search_card_bytes = b""
                            if image_url:
                                print(
                                    "[SOCIAL XIAOHONGSHU PREVIEW REJECTED]",
                                    "reason=blur_or_placeholder",
                                    title[:120],
                                )
                    elif platform == "youtube":
                        # Preserve only the title-bound native thumbnail. A
                        # whole search-card/page crop can include unrelated
                        # shelves and is not video evidence.
                        search_card_bytes = _download_post_image_jpeg(
                            page, image_url
                        )
                        if not _meaningful_raster_evidence(search_card_bytes):
                            search_card_bytes = b""
                    else:
                        search_card_bytes = _capture_clip_jpeg(
                            page,
                            card_data.get("clip"),
                            quality=76,
                        )
                    search_visual_frames = []
                    search_local_paths = []
                    if search_card_bytes:
                        search_visual_frames.append(
                            base64.b64encode(search_card_bytes).decode("ascii")
                        )
                        local_path = _persist_social_image_bytes(
                            search_card_bytes,
                            platform,
                            expected_url or page.url,
                            title,
                            "search-card",
                        )
                        if local_path:
                            search_local_paths.append(local_path)
                    url = direct_card_url
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
                        try:
                            if locator is None:
                                if not _click_fresh_social_title_node(page, title):
                                    raise RuntimeError("fresh title node unavailable")
                            else:
                                locator.click(timeout=4000)
                        except Exception:
                            # Reactive result grids can replace the title node
                            # between lookup and click. Re-find and click in one
                            # in-page operation before trying a locator again.
                            if not _click_fresh_social_title_node(page, title):
                                retry_locator = page.get_by_text(title, exact=True)
                                if retry_locator.count() < 1:
                                    retry_locator = page.get_by_text(
                                        title, exact=False
                                    )
                                if retry_locator.count() < 1:
                                    raise
                                retry_locator.first.evaluate(
                                    r"""
                                    (node) => {
                                        const clickable = node.closest(
                                            'a[href], button, [role="link"], ' +
                                            '[class*="note-item"], ' +
                                            '[class*="feed-card"]'
                                        ) || node;
                                        clickable.click();
                                    }
                                    """
                                )
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
                    source_url = _allowed_social_page_url(
                        platform,
                        expected_url or page.url,
                    )
                    if not url and not source_url:
                        continue
                    resolved.append(
                        {
                            "platform": platform,
                            "post_title": title,
                            "url": url or source_url,
                            "post_url": url,
                            "source_url": source_url,
                            "visible_text": visible_text,
                            "image_url": image_url,
                            "opened_by_click": opened_by_click,
                            "evidence_level": (
                                "opened_candidate" if url else "search_only"
                            ),
                            "visual_frames": search_visual_frames,
                            "local_image_paths": search_local_paths,
                            "visual_assets": [
                                {
                                    "kind": "search_preview",
                                    "label": "搜索结果预览",
                                    "frame": frame,
                                    "local_path": (
                                        search_local_paths[index]
                                        if index < len(search_local_paths) else ""
                                    ),
                                }
                                for index, frame in enumerate(search_visual_frames)
                            ],
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
    """Read the social page, retrying one empty Bilibili first load in place."""

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
        page_context = getattr(page, "context", None)
        if page_context is not None:
            managed_browser.keep_page_background(page_context, page)

        response_cache_key = ""
        if platform == "bilibili":
            response_cache_key = _bilibili_search_cache_key(
                expected_url or page.url
            )
            if response_cache_key:
                # open_social_search() used a short-lived Playwright CDP
                # connection. Reattach the native-response listener on this
                # live connection so it also observes the bounded reload.
                page.on(
                    "response",
                    lambda response: _store_bilibili_search_response(
                        response_cache_key, response
                    ),
                )
            try:
                page.wait_for_selector(
                    (
                        '.bili-video-card, .video-list-item, '
                        '.search-all-list-item, [class*="bili-video-card"]'
                    ),
                    state="attached",
                    timeout=7000,
                )
            except Exception:
                print("[SOCIAL RESULT WAIT] no_video_card_after_7s")

            initial_response_candidates = list(
                _BILIBILI_SEARCH_RESPONSE_CANDIDATES.get(
                    response_cache_key, []
                )
            )
            initial_dom_candidates = _extract_post_candidates(
                page, platform
            )
            if not initial_response_candidates and not initial_dom_candidates:
                print("[SOCIAL BILIBILI EMPTY FIRST LOAD]", "reload=1")
                try:
                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=12000,
                    )
                except Exception as error:
                    print(
                        "[SOCIAL BILIBILI RELOAD CONTINUES]",
                        repr(error),
                    )
                page.wait_for_timeout(3500)
                try:
                    page.wait_for_selector(
                        (
                            '.bili-video-card, .video-list-item, '
                            '.search-all-list-item, [class*="bili-video-card"]'
                        ),
                        state="attached",
                        timeout=10000,
                    )
                except Exception:
                    print(
                        "[SOCIAL BILIBILI RELOAD WAIT]",
                        "no_video_card_after_10s",
                    )
                initial_response_candidates = list(
                    _BILIBILI_SEARCH_RESPONSE_CANDIDATES.get(
                        response_cache_key, []
                    )
                )
                initial_dom_candidates = _extract_post_candidates(
                    page, platform
                )
                print(
                    "[SOCIAL BILIBILI RELOAD RESULT]",
                    "native=" + str(len(initial_response_candidates)),
                    "dom=" + str(len(initial_dom_candidates)),
                )
        elif platform == "youtube":
            _dismiss_youtube_consent(page)
            youtube_result_selector = (
                "ytd-video-renderer, ytd-grid-video-renderer, "
                "ytd-rich-item-renderer, ytd-reel-item-renderer, "
                "ytm-shorts-lockup-view-model-v2, ytd-rich-grid-media, "
                "yt-lockup-view-model"
            )
            try:
                page.wait_for_selector(
                    youtube_result_selector,
                    state="attached",
                    timeout=8000,
                )
            except Exception:
                print("[SOCIAL YOUTUBE RESULT WAIT] no_video_card_after_8s")
            initial_response_candidates = []
            initial_dom_candidates = _extract_post_candidates(page, platform)
            if not initial_dom_candidates:
                print("[SOCIAL YOUTUBE EMPTY FIRST LOAD]", "reload=1")
                try:
                    page.reload(
                        wait_until="domcontentloaded",
                        timeout=12000,
                    )
                except Exception as error:
                    print("[SOCIAL YOUTUBE RELOAD CONTINUES]", repr(error))
                _dismiss_youtube_consent(page)
                try:
                    page.wait_for_selector(
                        youtube_result_selector,
                        state="attached",
                        timeout=10000,
                    )
                except Exception:
                    print(
                        "[SOCIAL YOUTUBE RELOAD WAIT]",
                        "no_video_card_after_10s",
                    )
                initial_dom_candidates = _extract_post_candidates(page, platform)
                print(
                    "[SOCIAL YOUTUBE RELOAD RESULT]",
                    "dom=" + str(len(initial_dom_candidates)),
                )
        else:
            initial_response_candidates = []
            initial_dom_candidates = []

        snapshots = []
        visual_frames = []
        post_candidates = []
        seen_candidate_urls = set()
        response_candidates = list(initial_response_candidates)
        if platform == "bilibili":
            print(
                "[SOCIAL BILIBILI RESPONSE MERGE]",
                "candidates=" + str(len(response_candidates)),
            )
        for index in range(4):
            snapshot = page.locator("body").inner_text(timeout=15000)
            snapshots.append(snapshot)
            iteration_candidates = _extract_post_candidates(page, platform)
            if index == 0:
                iteration_candidates = (
                    response_candidates
                    + initial_dom_candidates
                    + iteration_candidates
                )
            for candidate in iteration_candidates:
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
            search_frame_limit = 0 if platform in ("reddit", "youtube") else (
                1 if platform == "xiaohongshu" else MAX_VISUAL_FRAMES
            )
            if platform == "xiaohongshu":
                try:
                    body_locator = page.locator("body")
                    if not callable(getattr(body_locator, "count", None)):
                        search_frame_limit = MAX_VISUAL_FRAMES
                except Exception:
                    search_frame_limit = MAX_VISUAL_FRAMES
            if index < search_frame_limit:
                try:
                    image_bytes = _capture_page_jpeg(page, quality=60)
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
        visible_text = _compose_social_visible_text(
            snapshots, post_candidates
        )
        print(
            "[SOCIAL DOM COUNTS]",
            _social_dom_diagnostics(page),
        )
        print(
            "[SOCIAL POST CANDIDATE SAMPLE]",
            [
                {
                    "kind": item.get("source_kind"),
                    "url": item.get("url"),
                    "text": str(item.get("visible_text") or "")[:180],
                }
                for item in post_candidates[:3]
            ],
        )
        print(
            "[SOCIAL RESULT CARD TEXT]",
            "items=" + str(len(post_candidates)),
            "chars=" + str(len(visible_text)),
        )
        if response_cache_key:
            _BILIBILI_SEARCH_RESPONSE_CANDIDATES.pop(
                response_cache_key, None
            )


        return {
            "platform": platform,
            "url": page.url,
            "title": page.title(),
            "visible_text": visible_text,
            "visual_frames": visual_frames[:MAX_VISUAL_FRAMES],
            "post_candidates": post_candidates,
        }


def _media_is_post_content(locator):
    try:
        return bool(
            locator.evaluate(
                r"""
                (node) => {
                    if (!node || !node.closest) return false;
                    if (node.closest(
                        'nav, aside, header, footer, [role="dialog"] ' +
                        '[class*="login"], [class*="signup"], ' +
                        '[class*="avatar"], [class*="sidebar"], ' +
                        '[class*="navigation"], [class*="recommend"]'
                    )) return false;
                    const source = (
                        node.currentSrc || node.src || node.poster || ''
                    ).toLowerCase();
                    const alt = (node.alt || '').toLowerCase();
                    if (/avatar|emoji|logo|icon|sprite/.test(source + ' ' + alt)) {
                        return false;
                    }
                    return true;
                }
                """
            )
        )
    except Exception:
        return True


def _post_container_selectors(platform):
    return {
        "reddit": (
            "shreddit-post",
            "article",
            '[data-testid="post-container"]',
        ),
        "xiaohongshu": (
            '.note-content',
            '[class*="note-content"]',
            '[class*="detail-content"]',
            '[class*="note-detail"]',
        ),
        "bilibili": (
            '.video-container',
            '.video-info-container',
            '[class*="video-container"]',
        ),
        "youtube": (
            'ytd-watch-flexy #primary',
            'ytd-watch-metadata',
            'ytd-reel-video-renderer[is-active]',
            'ytd-reel-video-renderer[aria-hidden="false"]',
        ),
        "instagram": ("article", "main article"),
        "x": ("article", '[data-testid="tweet"]'),
    }.get(platform, ("article", "main"))


def _capture_post_visual_frames(page, maximum=2, platform=""):
    """Capture post-bound media and content, excluding login/site chrome."""

    maximum = min(max(int(maximum or 0), 1), 2)
    frame_bytes = []
    content_api_available = True
    try:
        media = page.locator("img, video")
        if not callable(getattr(media, "count", None)):
            content_api_available = False
            raise AttributeError("locator count is unavailable")
        count = min(int(media.count()), 100)
        candidates = []
        for index in range(count):
            locator = media.nth(index)
            if not _media_is_post_content(locator):
                continue
            try:
                box = locator.bounding_box()
            except Exception:
                continue
            if not isinstance(box, dict):
                continue
            width = float(box.get("width") or 0)
            height = float(box.get("height") or 0)
            if width < 240 or height < 180:
                continue
            candidates.append((width * height, locator))
        candidates.sort(key=lambda value: value[0], reverse=True)
        for _area, locator in candidates[:6]:
            image_bytes = _capture_locator_jpeg(page, locator, quality=78)
            if image_bytes and image_bytes not in frame_bytes:
                frame_bytes.append(image_bytes)
                break
    except Exception as error:
        print("[SOCIAL POST MEDIA CAPTURE ERROR]", repr(error))

    container_candidates = []
    for selector in _post_container_selectors(platform):
        try:
            locators = page.locator(selector)
            for index in range(min(int(locators.count()), 8)):
                locator = locators.nth(index)
                box = locator.bounding_box()
                if not isinstance(box, dict):
                    continue
                width = float(box.get("width") or 0)
                height = float(box.get("height") or 0)
                if width >= 280 and height >= 140:
                    container_candidates.append((width * height, locator))
        except Exception:
            continue
    container_candidates.sort(key=lambda value: value[0], reverse=True)
    for _area, locator in container_candidates[:5]:
        image_bytes = _capture_locator_jpeg(page, locator, quality=68)
        if image_bytes and image_bytes not in frame_bytes:
            frame_bytes.append(image_bytes)
            break

    # Unknown platforms and compatibility fakes retain a bounded viewport
    # fallback. Known platforms deliberately omit it in a real browser so a
    # login/sidebar image can never masquerade as post evidence.
    if not frame_bytes and (not platform or not content_api_available):
        image_bytes = _capture_page_jpeg(page, quality=68)
        if image_bytes:
            frame_bytes.append(image_bytes)
    return [
        base64.b64encode(value).decode("ascii")
        for value in frame_bytes[:maximum]
    ]


def _detail_page_is_readable(platform, page_url, visible_text):
    if not _allowed_social_url(platform, page_url):
        return False
    text = " ".join(str(visible_text or "").split()).strip()
    # Short text posts are valid evidence; the URL boundary and shell markers
    # below are more reliable than a large minimum character count.
    if len(text) < 6:
        return False
    lowered = text.casefold()
    generic_only_markers = (
        "about rednote terms of service privacy policy",
        "continue with google continue with apple continue with phone number",
    )
    if any(marker in lowered for marker in generic_only_markers) and len(text) < 500:
        return False
    rednote_shell_markers = (
        "about rednote terms of service privacy policy",
        "search rednote",
        "for you fashion food beauty",
    )
    if platform == "xiaohongshu" and sum(
        marker in lowered for marker in rednote_shell_markers
    ) >= 2:
        return False
    return True


def inspect_social_post_details(targets):
    """Open up to seven grounded post links and read visible detail data."""

    safe_targets = []
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict):
            continue
        platform = str(target.get("platform") or "").strip()
        post_url = _allowed_social_url(
            platform,
            target.get("post_url") or target.get("url"),
        )
        source_url = _allowed_social_page_url(
            platform,
            target.get("source_url") or target.get("url"),
        )
        post_title = str(target.get("post_title") or "").strip()[:300]
        if not post_title or (not post_url and not source_url):
            continue
        search_visual_frames = [
            str(value).strip()
            for value in target.get("visual_frames", [])[:2]
            if str(value).strip()
        ] if isinstance(target.get("visual_frames"), list) else []
        search_local_paths = [
            str(value).strip()
            for value in target.get("local_image_paths", [])[:2]
            if str(value).strip()
        ] if isinstance(target.get("local_image_paths"), list) else []
        search_visual_assets = [
            value for value in target.get("visual_assets", [])[:1]
            if isinstance(value, dict)
        ] if isinstance(target.get("visual_assets"), list) else []
        if not search_visual_assets:
            search_visual_assets = [
                {
                    "kind": "search_preview",
                    "label": "搜索结果预览",
                    "frame": frame,
                    "local_path": (
                        search_local_paths[index]
                        if index < len(search_local_paths) else ""
                    ),
                }
                for index, frame in enumerate(search_visual_frames[:1])
            ]
        safe_targets.append(
            {
                "platform": platform,
                "url": post_url or source_url,
                "post_url": post_url,
                "source_url": source_url or post_url,
                "post_title": post_title,
                "search_image_url": _normalize_social_image_url(
                    platform, target.get("image_url")
                ),
                "search_visible_text": str(
                    target.get("visible_text") or ""
                ).strip()[:1400],
                "search_visible_time": _visible_social_time_in_text(
                    target.get("visible_text")
                ) if platform in ("xiaohongshu", "youtube") else "",
                "search_visual_frames": search_visual_frames,
                "search_local_image_paths": search_local_paths,
                "search_visual_assets": search_visual_assets,
                "evidence_level": str(
                    target.get("evidence_level") or (
                        "opened_candidate" if post_url else "search_only"
                    )
                ),
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
            if not target["post_url"]:
                details.append(
                    {
                        **target,
                        "url": target["source_url"],
                        "visible_text": target["search_visible_text"],
                        "image_url": (
                            target["search_image_url"]
                            if target["search_visual_assets"] else ""
                        ),
                        "visual_frame": (
                            target["search_visual_frames"][0]
                            if target["search_visual_frames"] else ""
                        ),
                        "visual_frames": target["search_visual_frames"],
                        "local_image_paths": target[
                            "search_local_image_paths"
                        ],
                        "visual_assets": target["search_visual_assets"],
                        "visible_time_text": target["search_visible_time"],
                        "evidence_level": "search_only",
                    }
                )
                continue
            page = context.new_page()
            managed_browser.keep_page_background(context, page)
            try:
                try:
                    page.goto(
                        target["post_url"],
                        wait_until="domcontentloaded",
                        timeout=8000,
                    )
                except PlaywrightTimeoutError:
                    print(
                        "[SOCIAL POST NAVIGATION CONTINUES]",
                        target["post_url"],
                    )
                if target["platform"] == "youtube":
                    _dismiss_youtube_consent(page)
                    try:
                        page.wait_for_selector(
                            (
                                '#movie_player, ytd-watch-metadata, '
                                'ytd-reel-video-renderer[is-active], '
                                'video.html5-main-video'
                            ),
                            state="attached",
                            timeout=5500,
                        )
                    except Exception:
                        print("[SOCIAL YOUTUBE DETAIL WAIT] player_not_attached")
                page.wait_for_timeout(
                    2200 if target["platform"] == "youtube" else 1600
                )
                visible_text = page.locator("body").inner_text(timeout=12000)
                actual_url = _allowed_social_url(target["platform"], page.url)
                if (
                    target["platform"] == "youtube"
                    and _youtube_video_identity(actual_url)
                    != _youtube_video_identity(target["post_url"])
                ):
                    print(
                        "[SOCIAL YOUTUBE DETAIL ID MISMATCH]",
                        "expected=" + _youtube_video_identity(target["post_url"]),
                        "actual=" + _youtube_video_identity(actual_url),
                    )
                    actual_url = ""
                youtube_metadata = (
                    _youtube_video_metadata(page)
                    if target["platform"] == "youtube" else {}
                )
                youtube_metadata_id = str(
                    youtube_metadata.get("video_id") or ""
                ).strip()
                if (
                    target["platform"] == "youtube"
                    and youtube_metadata_id
                    and youtube_metadata_id
                    != _youtube_video_identity(target["post_url"])
                ):
                    print(
                        "[SOCIAL YOUTUBE PLAYER ID MISMATCH]",
                        "expected=" + _youtube_video_identity(target["post_url"]),
                        "player=" + youtube_metadata_id,
                    )
                    actual_url = ""
                readable_text = visible_text
                if target["platform"] == "youtube":
                    readable_text = _bounded_youtube_video_text(
                        page,
                        target["post_title"],
                        metadata=youtube_metadata,
                    ) or visible_text
                if not _detail_page_is_readable(
                    target["platform"],
                    actual_url,
                    readable_text,
                ):
                    print(
                        "[SOCIAL POST DETAIL INVALID]",
                        target["platform"],
                        target["post_title"][:120],
                    )
                    details.append(
                        {
                            **target,
                            "url": target["source_url"] or target["post_url"],
                            "visible_text": target["search_visible_text"],
                            "image_url": (
                                target["search_image_url"]
                                if target["search_visual_assets"] else ""
                            ),
                            "visual_frame": (
                                target["search_visual_frames"][0]
                                if target["search_visual_frames"] else ""
                            ),
                            "visual_frames": target["search_visual_frames"],
                            "local_image_paths": target[
                                "search_local_image_paths"
                            ],
                            "visual_assets": target["search_visual_assets"],
                            "visible_time_text": target["search_visible_time"],
                            "evidence_level": "search_only",
                        }
                    )
                    continue
                detail_visible_text = str(visible_text or "").strip()[:12000]
                detail_visible_time = ""
                if target["platform"] == "reddit":
                    bounded_reddit_text = _bounded_reddit_post_text(page)
                    if bounded_reddit_text:
                        detail_visible_text = bounded_reddit_text
                elif target["platform"] == "xiaohongshu":
                    bounded_note_text = _bounded_xiaohongshu_post_text(page)
                    if not bounded_note_text:
                        print(
                            "[SOCIAL POST DETAIL SCOPE INVALID]",
                            target["platform"],
                            target["post_title"][:120],
                        )
                        details.append(
                            {
                                **target,
                                "url": target["source_url"] or target["post_url"],
                                "visible_text": target["search_visible_text"],
                                "image_url": (
                                    target["search_image_url"]
                                    if target["search_visual_assets"] else ""
                                ),
                                "visual_frame": (
                                    target["search_visual_frames"][0]
                                    if target["search_visual_frames"] else ""
                                ),
                                "visual_frames": target["search_visual_frames"],
                                "local_image_paths": target[
                                    "search_local_image_paths"
                                ],
                                "visual_assets": target["search_visual_assets"],
                                "visible_time_text": target["search_visible_time"],
                                "evidence_level": "search_only",
                            }
                        )
                        continue
                    detail_visible_text = bounded_note_text
                    detail_visible_time = _xiaohongshu_visible_post_time(page)
                elif target["platform"] == "bilibili":
                    bounded_video_text = _bounded_bilibili_video_text(
                        page, target["post_title"]
                    )
                    detail_visible_text = (
                        bounded_video_text or target["search_visible_text"]
                    )
                elif target["platform"] == "youtube":
                    bounded_video_text = _bounded_youtube_video_text(
                        page,
                        target["post_title"],
                        metadata=youtube_metadata,
                    )
                    detail_visible_text = (
                        bounded_video_text or target["search_visible_text"]
                    )
                    detail_visible_time = _youtube_published_time(
                        youtube_metadata
                    )
                captured_assets = _capture_social_post_assets(
                    page,
                    target["platform"],
                    fallback_image_url=target["search_image_url"],
                )
                visual_frames = []
                local_image_paths = []
                visual_assets = []
                for image_index, asset in enumerate(captured_assets, start=1):
                    if not isinstance(asset, dict):
                        continue
                    image_bytes = asset.get("image_bytes")
                    if not isinstance(image_bytes, (bytes, bytearray)):
                        continue
                    frame = base64.b64encode(bytes(image_bytes)).decode("ascii")
                    visual_frames.append(frame)
                    local_path = _persist_social_image_bytes(
                        image_bytes,
                        target["platform"],
                        actual_url or target["post_url"],
                        target["post_title"],
                        str(asset.get("kind") or "image") + "-" + str(image_index),
                    )
                    if local_path:
                        local_image_paths.append(local_path)
                    visual_assets.append(
                        {
                            "kind": str(asset.get("kind") or "media")[:24],
                            "label": str(asset.get("label") or "图片")[:40],
                            "frame": frame,
                            "local_path": local_path,
                        }
                    )
                visual_frame = visual_frames[0] if visual_frames else ""
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
                # Opened video/Xiaohongshu cards must use only downloaded,
                # validated bound assets. An arbitrary page image can be a
                # recommendation thumbnail, avatar, ad or loading placeholder.
                if target["platform"] == "bilibili":
                    image_url = ""
                elif target["platform"] in ("youtube", "xiaohongshu"):
                    image_url = ""
                else:
                    image_url = target["search_image_url"]
                if (
                    not image_url
                    and target["platform"] != "bilibili"
                    and target["platform"] != "youtube"
                    and target["platform"] != "xiaohongshu"
                ):
                    for image in images if isinstance(images, list) else []:
                        candidate = _normalize_social_image_url(
                            target["platform"], image.get("url")
                        )
                        if candidate:
                            image_url = candidate
                            break
                details.append(
                    {
                        **target,
                        "url": actual_url or target["post_url"],
                        "visible_text": detail_visible_text,
                        "image_url": image_url,
                        "visual_frame": visual_frame,
                        "visual_frames": visual_frames,
                        "local_image_paths": local_image_paths,
                        "visual_assets": visual_assets,
                        "visible_time_text": detail_visible_time,
                        "youtube_author": (
                            str(youtube_metadata.get("author") or "").strip()[:220]
                            if target["platform"] == "youtube" else ""
                        ),
                        "youtube_channel_id": (
                            str(youtube_metadata.get("channel_id") or "").strip()[:120]
                            if target["platform"] == "youtube" else ""
                        ),
                        "youtube_channel_url": (
                            str(youtube_metadata.get("channel_url") or "").strip()[:500]
                            if target["platform"] == "youtube" else ""
                        ),
                        "youtube_channel_handle": (
                            str(youtube_metadata.get("channel_handle") or "").strip()[:80]
                            if target["platform"] == "youtube" else ""
                        ),
                        "evidence_level": (
                            "opened_multimodal" if visual_frames else "opened_text"
                        ),
                    }
                )
            except Exception as error:
                print("[SOCIAL POST DETAIL ERROR]", repr(error))
                details.append(
                    {
                        **target,
                        "visible_text": target["search_visible_text"],
                        "image_url": (
                            target["search_image_url"]
                            if target["search_visual_assets"] else ""
                        ),
                        "visual_frame": (
                            target["search_visual_frames"][0]
                            if target["search_visual_frames"] else ""
                        ),
                        "visual_frames": target["search_visual_frames"],
                        "local_image_paths": target[
                            "search_local_image_paths"
                        ],
                        "visual_assets": target["search_visual_assets"],
                        "visible_time_text": target["search_visible_time"],
                        "evidence_level": "search_only",
                    }
                )
            finally:
                try:
                    page.close(run_before_unload=False)
                except Exception:
                    pass
    return details

def close_social_browser():
    """Close only social tabs; keep Bekki's shared browser running."""

    from playwright.sync_api import sync_playwright

    if not cdp_is_ready():
        return

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                CDP_URL
            )
            closed_count = 0
            for context in browser.contexts:
                for page in list(context.pages):
                    try:
                        hostname = str(
                            urlparse(page.url).hostname or ""
                        ).lower()
                    except ValueError:
                        hostname = ""
                    if not any(
                        hostname == domain or hostname.endswith("." + domain)
                        for domains in SOCIAL_DOMAINS.values()
                        for domain in domains
                    ):
                        continue
                    try:
                        page.close(run_before_unload=False)
                        closed_count += 1
                    except Exception as error:
                        print(
                            "[SOCIAL TAB CLOSE ERROR]",
                            repr(error),
                        )
        print("[SOCIAL BROWSER TABS CLOSED]", closed_count)

    except Exception as error:
        print(
            "[SOCIAL BROWSER CLOSE ERROR]",
            repr(error),
        )
    finally:
        _BILIBILI_SEARCH_RESPONSE_CANDIDATES.clear()
