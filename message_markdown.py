# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Safe Markdown and ordered evidence-block helpers for Bekki's chat UI.

The model continues to communicate with Python through JSON.  Only visible
message text is rendered as Markdown.  Search and recommendation evidence is
kept structured so context, media and navigation can never drift apart.
"""

import re


MAX_MESSAGE_MARKDOWN = 24_000
MAX_CARD_CONTEXT_MARKDOWN = 3_600


def _bounded_text(value, limit):
    if not isinstance(value, str):
        return ""
    value = value.replace("\x00", "")
    value = "".join(
        character
        for character in value
        if character in "\n\t" or ord(character) >= 32
    )
    return value[:limit].strip()


def bounded_markdown(value, limit=MAX_MESSAGE_MARKDOWN):
    """Return bounded display text without interpreting it as Markdown yet."""

    return _bounded_text(value, limit)


def escape_markdown_text(value, limit=600):
    """Escape untrusted card/source text while preserving readable content."""

    text = _bounded_text(str(value) if value is not None else "", limit)
    text = " ".join(text.split())
    # Card titles and snippets come from web pages.  They are content, never
    # Markdown instructions, so neutralise structural punctuation.
    return re.sub(r"([\\`*_{}\[\]()#+\-.!>|])", r"\\\1", text)


_MARKDOWN_IMAGE = re.compile(
    r"!\[([^\]\n]{0,200})\]\([^\)\n]{1,2048}\)",
    re.IGNORECASE,
)

_MARKDOWN_BLOCK = re.compile(
    r"(?m)^\s{0,3}(?:#{1,6}\s|[-+*]\s|\d{1,3}[.)]\s|>\s|```|~~~|"
    r"(?:\|[^\n]+\|\s*$))"
)
_MARKDOWN_INLINE = re.compile(
    r"(?:\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|`[^`\n]+`|"
    r"\[[^\]\n]+\]\([^\)\n]+\)|"
    r"(?<!\w)\*[^*\n]+\*(?!\w)|(?<!\w)_[^_\n]+_(?!\w))"
)


def has_rich_markdown(value):
    """Return true only when visible text actually needs rich rendering.

    Ordinary chat is deliberately kept on Qt's plain-text path.  Besides
    avoiding needless HTML conversion, that gives one QFont request ownership
    of the whole line instead of allowing the rich-text engine to fragment a
    CJK sentence into independently matched spans.
    """

    text = _bounded_text(str(value) if value is not None else "", MAX_MESSAGE_MARKDOWN)
    return bool(_MARKDOWN_BLOCK.search(text) or _MARKDOWN_INLINE.search(text))


def sanitize_markdown(value, limit=MAX_MESSAGE_MARKDOWN):
    """Return a bounded, display-only Markdown subset.

    Raw HTML and Markdown images are deliberately disabled.  Images belong to
    structured evidence blocks where their source link and context are known.
    Ordinary links remain visible, while the UI independently permits only
    public HTTPS navigation.
    """

    text = _bounded_text(str(value) if value is not None else "", limit)
    text = _MARKDOWN_IMAGE.sub(
        lambda match: "🖼 " + (match.group(1).strip() or "图片"),
        text,
    )
    # QTextDocument accepts embedded HTML inside Markdown.  Escape it before
    # parsing so model or page text cannot create active UI elements.
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def apply_highlights(markdown, highlights):
    """Translate legacy semantic highlights into safe Markdown emphasis."""

    text = _bounded_text(
        str(markdown) if markdown is not None else "",
        MAX_MESSAGE_MARKDOWN,
    )
    if not isinstance(highlights, list):
        return text

    ranges = []
    for item in highlights[:8]:
        if not isinstance(item, dict):
            continue
        value = str(item.get("text") or "")
        style = str(item.get("style") or "").strip().lower()
        start = text.find(value) if value else -1
        end = start + len(value)
        if start < 0 or style not in {
            "important", "warning", "critical", "technical"
        }:
            continue
        if any(start < old_end and end > old_start for old_start, old_end, _ in ranges):
            continue
        ranges.append((start, end, style))

    if not ranges:
        return text

    ranges.sort(key=lambda item: item[0])
    parts = []
    cursor = 0
    for start, end, style in ranges:
        parts.append(text[cursor:start])
        value = text[start:end]
        if style == "technical" and "`" not in value:
            parts.append("`" + value + "`")
        else:
            parts.append("**" + value + "**")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _metadata_lines(metadata):
    if not isinstance(metadata, dict):
        return []
    labels = (
        ("price", "价格"),
        ("currency", "货币"),
        ("author", "作者"),
        ("published_at", "时间"),
        ("merchant", "商家"),
        ("brand", "品牌"),
        ("brand_reliability", "品牌证据"),
        ("profile_fit", "需求匹配度"),
        ("stock", "库存"),
        ("popularity_status", "热度"),
        ("popularity_evidence", "热度依据"),
        ("rating", "评分"),
        ("review_count", "评价数"),
        ("likes", "点赞"),
        ("comments", "评论"),
        ("shares", "分享"),
        ("duration", "时长"),
        ("timestamp", "时间点"),
        ("location", "地点"),
    )
    lines = []
    for key, label in labels:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        lines.append(
            "- **" + label + "：** " + escape_markdown_text(value, 180)
        )
    return lines


def card_context_markdown(card):
    """Build the context portion of one card without importing its media/link."""

    if not isinstance(card, dict):
        return ""
    explicit = _bounded_text(
        card.get("context_markdown"),
        MAX_CARD_CONTEXT_MARKDOWN,
    )
    if explicit:
        return explicit

    title = escape_markdown_text(card.get("title"), 180)
    summary = escape_markdown_text(card.get("summary"), 900)
    lines = []
    if title:
        lines.append("### " + title)
    if summary:
        lines.extend(("", summary))

    metadata_lines = _metadata_lines(card.get("metadata"))
    if metadata_lines:
        lines.extend(("", *metadata_lines))

    requirements = card.get("requirements")
    if isinstance(requirements, list):
        requirement_lines = []
        symbols = {"MATCH": "✅", "MISMATCH": "❌", "UNKNOWN": "❔"}
        for item in requirements[:6]:
            if not isinstance(item, dict):
                continue
            label = escape_markdown_text(
                item.get("label")
                or item.get("requirement")
                or item.get("name")
                or item.get("text"),
                180,
            )
            if not label:
                continue
            state = str(item.get("status") or "UNKNOWN").upper()
            evidence = escape_markdown_text(item.get("evidence"), 240)
            line = "- " + symbols.get(state, "❔") + " " + label
            if evidence:
                line += " — " + evidence
            requirement_lines.append(line)
        if requirement_lines:
            lines.extend(("", "#### 匹配情况", *requirement_lines))

    sections = card.get("sections")
    if isinstance(sections, list):
        for section in sections[:6]:
            if not isinstance(section, dict):
                continue
            kind = str(section.get("kind") or "").lower()
            section_lines = []
            if kind == "facts" and isinstance(section.get("items"), dict):
                section_lines = [
                    "- **" + escape_markdown_text(key, 80) + "：** "
                    + escape_markdown_text(value, 240)
                    for key, value in list(section["items"].items())[:6]
                    if escape_markdown_text(key, 80)
                    and escape_markdown_text(value, 240)
                ]
            elif kind == "pros_cons":
                pros = section.get("pros") if isinstance(section.get("pros"), list) else []
                cons = section.get("cons") if isinstance(section.get("cons"), list) else []
                section_lines.extend(
                    "- ✅ " + escape_markdown_text(value, 240)
                    for value in pros[:3]
                    if escape_markdown_text(value, 240)
                )
                section_lines.extend(
                    "- ⚠️ " + escape_markdown_text(value, 240)
                    for value in cons[:3]
                    if escape_markdown_text(value, 240)
                )
            elif kind in {"fit", "warning", "note"}:
                label = escape_markdown_text(section.get("label"), 80)
                value = escape_markdown_text(section.get("text"), 300)
                if value:
                    section_lines = [
                        "- " + (("**" + label + "：** ") if label else "") + value
                    ]
            if section_lines:
                lines.extend(("", *section_lines))

    return _bounded_text("\n".join(lines), MAX_CARD_CONTEXT_MARKDOWN)


def evidence_block(card):
    """Return one ordered context -> graph(s) -> link presentation contract."""

    if not isinstance(card, dict):
        return {
            "context_markdown": "",
            "graphs": [],
            "graph_placeholder": True,
            "link": {"url": "", "label": "查看来源  ↗"},
        }

    card_type = str(card.get("type") or "article").lower()
    images = card.get("images")
    if not isinstance(images, list):
        images = []
    if not images and isinstance(card.get("image"), dict):
        images = [card.get("image")]
    image_limit = 4 if card_type == "social_post" else 1
    graphs = [value for value in images[:image_limit] if isinstance(value, dict)]
    metadata = card.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    link_label = (
        "查看商品  ↗" if card_type == "product"
        else "查看搜索页  ↗" if (
            card_type == "social_post"
            and str(metadata.get("link_target") or "").strip() == "search"
        )
        else "打开原帖  ↗" if card_type == "social_post"
        else "查看地点  ↗" if card_type == "place"
        else "查看来源  ↗"
    )
    return {
        "context_markdown": card_context_markdown(card),
        "graphs": graphs,
        "graph_placeholder": not bool(graphs),
        "link": {
            "url": str(card.get("url") or "").strip(),
            "label": link_label,
        },
    }
