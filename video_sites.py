# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Persistent registry of websites structurally verified as video sources."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlparse


SCHEMA_VERSION = 1
PROJECT_ROOT = Path(__file__).resolve().parent
REGISTRY_FILE = PROJECT_ROOT / "data" / "verified_video_sites.json"
_LOCK = threading.RLock()


def _nonnegative_int(value):
    """Read persisted counters without letting a corrupt file break startup."""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def normalize_domain(value):
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    if "://" in raw:
        try:
            raw = str(urlparse(raw).hostname or "").casefold()
        except ValueError:
            return ""
    raw = raw.removeprefix("www.").strip(" ./")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", raw):
        return ""
    if "." not in raw or ".." in raw:
        return ""
    if raw.endswith((".local", ".localhost", ".internal")):
        return ""
    return raw


def _empty_registry():
    return {"schema_version": SCHEMA_VERSION, "sites": {}}


def _normalized_alias(value):
    alias = re.sub(r"\s+", " ", str(value or "")).strip().casefold()[:80]
    if len(alias) < 2:
        return ""
    if len(alias) < 3 and not re.search(r"[\u3400-\u9fff]", alias):
        return ""
    if alias in {
        "视频", "影视", "电影", "电视剧", "动漫", "动画", "综艺",
        "首页", "播放", "在线观看", "video", "videos", "movie",
        "movies", "watch", "watch online", "home",
    }:
        return ""
    return alias


def _normalized_template(value, domain):
    template = str(value or "").strip()[:2000]
    if template.count("{query}") != 1:
        return ""
    try:
        parsed = urlparse(template.replace("{query}", "probe"))
    except ValueError:
        return ""
    host = normalize_domain(parsed.hostname)
    if parsed.scheme != "https" or not host:
        return ""
    if not (host == domain or host.endswith("." + domain)):
        return ""
    return template


def load_registry(path=None):
    target = Path(path) if path is not None else REGISTRY_FILE
    with _LOCK:
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return _empty_registry()
    sites = {}
    source_sites = raw.get("sites", {}) if isinstance(raw, dict) else {}
    if isinstance(source_sites, dict):
        for key, source in source_sites.items():
            domain = normalize_domain(key)
            if not domain or not isinstance(source, dict):
                continue
            aliases = []
            source_aliases = source.get("aliases", [])
            if not isinstance(source_aliases, (list, tuple)):
                source_aliases = []
            for value in source_aliases:
                alias = _normalized_alias(value)
                if alias and alias not in aliases:
                    aliases.append(alias)
            evidence_source = source.get("evidence")
            if not isinstance(evidence_source, dict):
                evidence_source = {}
            sites[domain] = {
                "domain": domain,
                "verified": bool(source.get("verified")),
                "aliases": aliases[:12],
                "search_url_template": _normalized_template(
                    source.get("search_url_template"), domain
                ),
                "first_verified_at": str(source.get("first_verified_at") or "")[:80],
                "last_verified_at": str(source.get("last_verified_at") or "")[:80],
                "verification_count": _nonnegative_int(
                    source.get("verification_count")
                ),
                "evidence": {
                    "detail_link_count": _nonnegative_int(
                        evidence_source.get("detail_link_count")
                    ),
                    "taxonomy_hit_count": _nonnegative_int(
                        evidence_source.get("taxonomy_hit_count")
                    ),
                    "media_element_count": _nonnegative_int(
                        evidence_source.get("media_element_count")
                    ),
                },
            }
    return {"schema_version": SCHEMA_VERSION, "sites": sites}


def _save_registry(registry, path=None):
    target = Path(path) if path is not None else REGISTRY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def is_verified(domain, path=None):
    normalized = normalize_domain(domain)
    if not normalized:
        return False
    item = load_registry(path).get("sites", {}).get(normalized, {})
    return bool(item.get("verified"))


def get_site(domain, path=None):
    normalized = normalize_domain(domain)
    item = load_registry(path).get("sites", {}).get(normalized)
    return dict(item) if isinstance(item, dict) else None


def match_aliases(message, path=None):
    """Return verified domains whose learned site names occur literally."""

    text = re.sub(r"\s+", " ", str(message or "")).casefold()
    matches = []
    for domain, item in load_registry(path).get("sites", {}).items():
        if not item.get("verified"):
            continue
        if any(alias and alias in text for alias in item.get("aliases", [])):
            matches.append(domain)
    return matches[:4]


def record_verified_site(
    domain,
    evidence,
    aliases=None,
    search_url_template="",
    path=None,
    now=None,
):
    """Persist only a site that already passed the structural verifier."""

    normalized = normalize_domain(domain)
    if not normalized:
        raise ValueError("invalid_video_site_domain")
    evidence = evidence if isinstance(evidence, dict) else {}
    detail_links = _nonnegative_int(evidence.get("detail_link_count"))
    taxonomy_hits = _nonnegative_int(evidence.get("taxonomy_hit_count"))
    media_elements = _nonnegative_int(evidence.get("media_element_count"))
    if not (
        (detail_links >= 6 and taxonomy_hits >= 2)
        or (detail_links >= 3 and taxonomy_hits >= 1 and media_elements >= 1)
    ):
        raise ValueError("insufficient_video_site_evidence")
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    with _LOCK:
        registry = load_registry(path)
        previous = registry["sites"].get(normalized, {})
        learned_aliases = list(previous.get("aliases", []))
        domain_alias = _normalized_alias(normalized.split(".", 1)[0])
        alias_values = aliases if isinstance(aliases, (list, tuple)) else []
        for value in [domain_alias, *alias_values]:
            alias = _normalized_alias(value)
            if alias and alias not in learned_aliases:
                learned_aliases.append(alias)
        template = _normalized_template(search_url_template, normalized)
        if not template:
            template = str(previous.get("search_url_template") or "")
        item = {
            "domain": normalized,
            "verified": True,
            "aliases": learned_aliases[:12],
            "search_url_template": template,
            "first_verified_at": str(
                previous.get("first_verified_at") or timestamp
            ),
            "last_verified_at": timestamp,
            "verification_count": _nonnegative_int(
                previous.get("verification_count")
            ) + 1,
            "evidence": {
                "detail_link_count": detail_links,
                "taxonomy_hit_count": taxonomy_hits,
                "media_element_count": media_elements,
            },
        }
        registry["sites"][normalized] = item
        _save_registry(registry, path)
    return dict(item)
