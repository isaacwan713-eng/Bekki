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
    seen_urls = set()

    for card in cards:
        safe_card = clean_card(card)

        if safe_card is None:
            continue

        url = safe_card["url"]

        if url in seen_urls:
            continue

        seen_urls.add(url)
        cleaned.append(safe_card)

        if len(cleaned) >= MAX_CARDS:
            break

    return cleaned