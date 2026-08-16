# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Validation for Bekki multimodal result cards."""

from urllib.parse import urlparse


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


def _clean_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}

    allowed_fields = {
        "author",
        "published_at",
        "price",
        "currency",
        "merchant",
        "stock",
        "rating",
        "review_count",
        "location",
        "captured_at",
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

    image_url = _clean_https_url(
        image.get("url")
    )

    if not image_url:
        return None

    source_url = _clean_https_url(
        image.get("source_url")
    )

    return {
        "url": image_url,
        "alt": _clean_text(
            image.get("alt"),
            200,
        ),
        "source_url": (
            source_url or None
        ),
    }


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

    return {
        "type": card_type,
        "title": title,
        "summary": _clean_text(
            card.get("summary"),
            MAX_SUMMARY_LENGTH,
        ),
        "url": url,
        "domain": domain,
        "image": _clean_image(
            card.get("image")
        ),
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
