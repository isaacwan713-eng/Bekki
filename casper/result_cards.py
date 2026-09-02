# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Validation for Bekki multimodal result cards."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import message_markdown


VALID_CARD_TYPES = {
    "article",
    "news",
    "product",
    "social_post",
    "place",
    "person",
    "provider",
    "service",
}

VALID_MATCH_STATES = {
    "MATCH",
    "MISMATCH",
    "UNKNOWN",
}

MAX_CARDS = 8
MAX_REQUIREMENTS = 12
MAX_TITLE_LENGTH = 180
MAX_SUMMARY_LENGTH = 600
MAX_URL_LENGTH = 2048
MAX_SECTIONS = 8
MAX_CONTEXT_MARKDOWN_LENGTH = message_markdown.MAX_CARD_CONTEXT_MARKDOWN


def _clean_text(
    value,
    maximum_length,
):
    if not isinstance(value, str):
        return ""

    return (
        " ".join(
            value.split()
        )[:maximum_length]
    )


def _clean_https_url(value):
    """Accept only public HTTPS URLs.

    Local files, data URLs and executable protocols
    must never enter a result card.
    """

    if not isinstance(value, str):
        return ""

    value = value.strip()[
        :MAX_URL_LENGTH
    ]

    if not value:
        return ""

    try:
        parsed = urlparse(value)

    except ValueError:
        return ""

    if parsed.scheme.lower() != "https":
        return ""

    if not parsed.netloc:
        return ""

    if (
        parsed.username
        or parsed.password
    ):
        return ""

    return value


def _social_media_cache_root():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Bekki"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Bekki"
    else:
        base = Path.home() / ".local" / "share" / "Bekki"
    return (base / "social_media_cache").resolve()


def _clean_local_image_path(value):
    """Accept only existing raster files created in Bekki's evidence cache."""

    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        path = Path(value.strip()).expanduser().resolve()
        cache_root = _social_media_cache_root()
        path.relative_to(cache_root)
        if not path.is_file():
            return ""
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            return ""
        if path.stat().st_size > 8 * 1024 * 1024:
            return ""
    except (OSError, ValueError):
        return ""
    return str(path)


def _clean_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}

    allowed_fields = {
        "author",
        "published_at",
        "price",
        "currency",
        "merchant",
        "brand",
        "brand_reliability",
        "profile_fit",
        "stock",
        "rating",
        "review_count",
        "location",
        "captured_at",
        "popularity_status",
        "popularity_evidence",
        "likes",
        "comments",
        "shares",
        "duration",
        "timestamp",
        "post_title",
        "evidence_level",
        "link_target",
    }

    cleaned = {}

    for key in allowed_fields:
        value = metadata.get(key)

        if value is None:
            continue

        if isinstance(
            value,
            (str, int, float, bool),
        ):
            cleaned[key] = value

    return cleaned


def _clean_image(image):
    if not isinstance(image, dict):
        return None

    image_url = _clean_https_url(image.get("url"))
    local_path = _clean_local_image_path(image.get("local_path"))

    if not image_url and not local_path:
        return None

    source_url = _clean_https_url(
        image.get("source_url")
    )

    return {
        "url": image_url,
        "local_path": local_path,
        "alt": _clean_text(
            image.get("alt"),
            200,
        ),
        "source_url": (
            source_url or None
        ),
        "label": _clean_text(image.get("label"), 40),
        "kind": _clean_text(image.get("kind"), 24),
        "timestamp": _clean_text(image.get("timestamp"), 40),
    }


def _clean_images(items, fallback=None):
    cleaned = []
    seen = set()
    if isinstance(items, list):
        gallery_contract = any(
            isinstance(item, dict)
            and str(item.get("kind") or "").strip().lower()
            in {"media", "text", "search_preview"}
            for item in items[:4]
        )
        image_limit = 4 if gallery_contract else 2
        candidates = items[:image_limit]
    else:
        image_limit = 2
        candidates = []
    if fallback is not None:
        candidates.append(fallback)
    for item in candidates:
        image = _clean_image(item)
        if not image:
            continue
        key = image.get("local_path") or image.get("url")
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(image)
        if len(cleaned) >= image_limit:
            break
    return cleaned


def _clean_requirements(items):
    if not isinstance(items, list):
        return []

    cleaned = []

    for item in items[
        :MAX_REQUIREMENTS
    ]:
        if not isinstance(item, dict):
            continue

        requirement = _clean_text(
            item.get("requirement"),
            180,
        )

        state = str(
            item.get(
                "status",
                "UNKNOWN",
            )
        ).upper().strip()

        if state not in VALID_MATCH_STATES:
            state = "UNKNOWN"

        evidence = _clean_text(
            item.get("evidence"),
            300,
        )

        if not requirement:
            continue

        cleaned.append(
            {
                "requirement": requirement,
                "status": state,
                "evidence": evidence,
            }
        )

    return cleaned


def _clean_sections(items):
    """Keep AI-selected content while bounding renderable section shapes."""
    if not isinstance(items, list):
        return []
    allowed = {"facts", "pros_cons", "fit", "warning", "note"}
    cleaned = []
    for item in items[:MAX_SECTIONS]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).lower().strip()
        if kind not in allowed:
            continue
        section = {"kind": kind}
        if kind == "facts":
            values = item.get("items", {})
            if not isinstance(values, dict):
                continue
            section["items"] = {
                _clean_text(str(key), 60): _clean_text(str(value), 180)
                for key, value in list(values.items())[:10]
                if _clean_text(str(key), 60) and _clean_text(str(value), 180)
            }
        elif kind == "pros_cons":
            for field in ("pros", "cons"):
                values = item.get(field, [])
                section[field] = (
                    [_clean_text(str(value), 180) for value in values[:5]
                     if _clean_text(str(value), 180)]
                    if isinstance(values, list) else []
                )
        else:
            section["label"] = _clean_text(item.get("label"), 80)
            section["text"] = _clean_text(item.get("text"), 300)
        cleaned.append(section)
    return cleaned


def clean_card(card):
    """Validate one AI/tool-produced result card."""

    if not isinstance(card, dict):
        return None

    card_type = str(
        card.get(
            "type",
            "article",
        )
    ).lower().strip()

    if card_type not in VALID_CARD_TYPES:
        card_type = "article"

    url = _clean_https_url(
        card.get("url")
    )

    # A card must always lead to a real page.
    if not url:
        return None

    title = _clean_text(
        card.get("title"),
        MAX_TITLE_LENGTH,
    )

    if not title:
        return None

    domain = _clean_text(
        card.get("domain"),
        120,
    ).lower()

    if not domain:
        try:
            domain = (
                urlparse(url)
                .netloc
                .lower()
                .removeprefix("www.")
            )

        except ValueError:
            domain = ""

    images = _clean_images(card.get("images"), card.get("image"))
    images = images[:4 if card_type == "social_post" else 1]
    return {
        "type": card_type,
        "title": title,
        "summary": _clean_text(
            card.get("summary"),
            MAX_SUMMARY_LENGTH,
        ),
        "context_markdown": message_markdown.bounded_markdown(
            card.get("context_markdown"),
            MAX_CONTEXT_MARKDOWN_LENGTH,
        ),
        "url": url,
        "domain": domain,
        "image": images[0] if images else None,
        "images": images,
        "metadata": _clean_metadata(
            card.get("metadata")
        ),
        "sections": _clean_sections(card.get("sections")),
        "requirements": (
            _clean_requirements(
                card.get("requirements")
            )
        ),
    }


def clean_cards(cards):
    """Return a bounded and deduplicated card list."""

    if not isinstance(cards, list):
        return []

    cleaned = []
    # A roundup can support several distinct recommendation candidates.  The
    # same evidence URL is therefore valid when the candidate title differs.
    seen_cards = set()

    for card in cards:
        safe_card = clean_card(card)

        if safe_card is None:
            continue

        key = (
            safe_card["url"],
            safe_card["title"].casefold(),
        )

        if key in seen_cards:
            continue

        seen_cards.add(key)
        cleaned.append(safe_card)

        if len(cleaned) >= MAX_CARDS:
            break

    return cleaned


def source_to_card(source):
    """Convert one search source into the same bound evidence contract as a card."""

    if not isinstance(source, dict):
        return None
    url = _clean_https_url(source.get("url"))
    if not url:
        return None
    domain = _clean_text(source.get("domain"), 120)
    title = _clean_text(source.get("title"), MAX_TITLE_LENGTH) or domain or "来源"
    summary = _clean_text(
        source.get("description") or source.get("summary"),
        MAX_SUMMARY_LENGTH,
    )
    content_type = str(source.get("content_type") or "").upper()
    card_type = "news" if content_type == "NEWS" else "article"
    image_url = source.get("image_url")
    image = (
        {
            "url": image_url,
            "alt": title,
            "source_url": url,
            "label": "来源图片",
            "kind": "media",
        }
        if image_url
        else None
    )
    return clean_card(
        {
            "type": card_type,
            "title": title,
            "summary": summary,
            "url": url,
            "domain": domain,
            "image": image,
            "metadata": {
                "published_at": source.get("published") or "",
            },
            "requirements": [],
        }
    )


def is_concrete_social_post_url(value):
    """Return True only for a platform-native post/detail URL, not search UI."""

    url = _clean_https_url(value)
    if not url:
        return False
    parsed = urlparse(url)
    host = str(parsed.hostname or "").casefold().rstrip(".")
    path = str(parsed.path or "").casefold()

    def on_domain(domain):
        return host == domain or host.endswith("." + domain)

    if on_domain("xiaohongshu.com") or on_domain("rednote.com"):
        return path.startswith("/explore/") or path.startswith(
            "/discovery/item/"
        )
    if on_domain("reddit.com"):
        parts = [part for part in path.split("/") if part]
        return len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments"
    if on_domain("bilibili.com"):
        return path.startswith("/video/") or path.startswith("/bangumi/play/")
    if on_domain("twitter.com") or on_domain("x.com"):
        parts = [part for part in path.split("/") if part]
        return len(parts) >= 3 and parts[1] == "status"
    if on_domain("instagram.com"):
        return path.startswith("/p/") or path.startswith("/reel/")
    return False


def cards_from_sources(sources, exclude_urls=None, limit=5):
    """Keep source order while removing links already represented by result cards."""

    if not isinstance(sources, list):
        return []
    excluded = {
        str(value).strip()
        for value in (exclude_urls or [])
        if str(value).strip()
    }
    cards = []
    seen = set(excluded)
    for source in sources:
        card = source_to_card(source)
        if not card or card["url"] in seen:
            continue
        seen.add(card["url"])
        cards.append(card)
        if len(cards) >= max(1, min(int(limit or 5), 8)):
            break
    return cards
