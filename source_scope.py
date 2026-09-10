"""Literal web-source constraints shared by MAGI, Melchior, and Casper.

The requested outcome and the place where it must be researched are separate
contracts. This module extracts only a site the user literally bound to a
search-like action; it never chooses the semantic search outcome.
"""

import re
from urllib.parse import urlparse


SOURCE_OPEN_WEB = "OPEN_WEB"
SOURCE_FIXED_SITES = "FIXED_SITES"
VALID_SOURCE_SCOPES = {SOURCE_OPEN_WEB, SOURCE_FIXED_SITES}

KNOWN_SITE_ALIASES = (
    (("bilibili", "b站", "哔哩哔哩"), "bilibili.com", "bilibili"),
    (("youtube", "油管"), "youtube.com", "youtube"),
    (("wikipedia", "wiki", "维基百科", "维基"), "wikipedia.org", None),
    (("xiaohongshu", "小红书"), "xiaohongshu.com", "xiaohongshu"),
    (("reddit", "红迪"), "reddit.com", "reddit"),
    (("instagram", "insta"), "instagram.com", "instagram"),
    (("x.com", "twitter", "推特"), "x.com", "x"),
)

_SEARCH_ACTION = re.compile(
    r"搜索|搜一下|搜一搜|检索|查一下|查看|查找|查询|查|核实|"
    r"验证|浏览|总结|收集|搜集|看看|找一下|"
    r"\b(?:search|look\s+up|check|verify|browse|inspect|research|"
    r"summarize|find)\b",
    re.IGNORECASE,
)
_SOURCE_BINDING = re.compile(
    r"去|到|在|从|通过|使用|用|只看|仅看|仅限|限定|"
    r"\b(?:on|in|at|from|via|using|only)\b",
    re.IGNORECASE,
)
_OFFICIAL_ONLY = re.compile(
    r"(?:只|仅)(?:接受|使用|采用|限于|限|看|查)?[^\n。；;]{0,40}官方|"
    r"官方(?:账号|账号|资料|来源|网站|网页|发布)[^\n。；;]{0,20}(?:为准|优先|限定)?|"
    r"official[^.;\n]{0,40}(?:only|exclusively)|"
    r"(?:only|exclusively)[^.;\n]{0,40}official",
    re.IGNORECASE,
)
_DOMAIN_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?"
    r"\.[a-z]{2,}(?:/[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?",
    re.IGNORECASE,
)
_SITE_OPERATOR_PATTERN = re.compile(
    r"(?<![a-z0-9_-])site\s*:\s*(?:https?://)?(?:www\.)?"
    r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?",
    re.IGNORECASE,
)


def normalize_domain(value):
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return ""
    host = str(parsed.hostname or "").casefold().removeprefix("www.").strip(".")
    if (
        not host
        or "." not in host
        or ".." in host
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host)
        or host.endswith((".local", ".internal", ".localhost"))
        or re.fullmatch(r"\d+(?:\.\d+){3}", host)
    ):
        return ""
    return host


def normalize_domains(values):
    domains = []
    for value in values if isinstance(values, list) else []:
        domain = normalize_domain(value)
        if domain and domain not in domains:
            domains.append(domain)
        if len(domains) >= 4:
            break
    return domains


def domain_matches(domain, allowed):
    domain = normalize_domain(domain)
    allowed = normalize_domain(allowed)
    return bool(domain and allowed and (
        domain == allowed or domain.endswith("." + allowed)
    ))


def _marker_present(text, marker):
    marker = marker.casefold()
    compact_text = re.sub(r"\s+", "", text)
    if any(ord(character) > 127 for character in marker):
        return marker in compact_text
    return re.search(
        r"(?<![a-z0-9])" + re.escape(marker) + r"(?![a-z0-9])",
        text,
        flags=re.IGNORECASE,
    ) is not None


def extract_fixed_sites(message):
    """Return only literal sites bound to a search/research action."""

    text = " ".join(str(message or "").split()).casefold()
    if not text or not _SEARCH_ACTION.search(text) or not _SOURCE_BINDING.search(text):
        return []
    sites = []
    for aliases, domain, _platform in KNOWN_SITE_ALIASES:
        if any(_marker_present(text, alias) for alias in aliases):
            if domain not in sites:
                sites.append(domain)
    for match in _DOMAIN_PATTERN.findall(text):
        domain = normalize_domain(match)
        if domain and domain not in sites:
            sites.append(domain)
    return sites[:4]


def official_only(message):
    return _OFFICIAL_ONLY.search(str(message or "")) is not None


def platforms_for_sites(sites):
    platforms = []
    normalized = normalize_domains(list(sites or []))
    for _aliases, domain, platform in KNOWN_SITE_ALIASES:
        if platform and any(domain_matches(site, domain) for site in normalized):
            if platform not in platforms:
                platforms.append(platform)
    return platforms


def route_contract(message):
    sites = extract_fixed_sites(message)
    has_search_action = _SEARCH_ACTION.search(str(message or "")) is not None
    return {
        "source_scope": SOURCE_FIXED_SITES if sites else SOURCE_OPEN_WEB,
        "requested_sites": sites,
        "official_only": bool(has_search_action and official_only(message)),
    }


def reconcile_magi_route(message, raw):
    """Attach literal source scope and remove semantic/source conflation."""

    if not isinstance(raw, dict):
        return raw
    contract = route_contract(message)
    if (
        contract["source_scope"] == SOURCE_OPEN_WEB
        and str(raw.get("search_scope") or "").upper().strip()
        == "MEDIA_WATCH"
    ):
        try:
            import media_watch

            media_sites = normalize_domains(
                media_watch.extract_requested_sites(message)
            )
        except (ImportError, AttributeError, TypeError, ValueError):
            media_sites = []
        if media_sites:
            contract = {
                "source_scope": SOURCE_FIXED_SITES,
                "requested_sites": media_sites,
                "official_only": False,
            }
    repaired = dict(raw)
    repaired.update(contract)
    if contract["source_scope"] != SOURCE_FIXED_SITES:
        return repaired

    previous_lane = str(repaired.get("lane") or "").upper().strip()
    repaired["lane"] = "SEARCH"
    search_scope = str(repaired.get("search_scope") or "").upper().strip()
    if not search_scope:
        search_scope = (
            "SOCIAL_RESEARCH"
            if str(repaired.get("social_scope") or "OTHER").upper().strip()
            == "SOCIAL_RESEARCH"
            else "OTHER"
        )
    if search_scope != "SOCIAL_RESEARCH":
        if str(repaired.get("social_scope") or "OTHER").upper().strip() == "SOCIAL_RESEARCH":
            repaired["social_scope"] = "OTHER"
            repaired["social_platforms"] = []
            print(
                "[MAGI SOURCE/PURPOSE SEPARATED]",
                "purpose=" + search_scope,
                "sites=" + ",".join(contract["requested_sites"]),
            )
    else:
        platforms = platforms_for_sites(contract["requested_sites"])
        if platforms:
            repaired["social_scope"] = "SOCIAL_RESEARCH"
            repaired["social_platforms"] = platforms
    if previous_lane != "SEARCH":
        print(
            "[MAGI FIXED SOURCE LANE]",
            "from=" + (previous_lane or "UNKNOWN"),
            "to=SEARCH",
        )
    return repaired


def _without_site_operators(query):
    text = _SITE_OPERATOR_PATTERN.sub(" ", str(query or ""))
    text = re.sub(r"\(\s*(?:OR\s*)*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:^|\s)OR(?=\s|$)", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip()


def constrain_query(query, sites):
    """Apply one canonical site restriction, replacing model-added ones."""

    sites = normalize_domains(list(sites or []))
    if not sites:
        return " ".join(str(query or "").split()).strip()
    text = _without_site_operators(query)
    clauses = ["site:" + site for site in sites]
    prefix = clauses[0] if len(clauses) == 1 else "(" + " OR ".join(clauses) + ")"
    return (prefix + " " + text).strip()[:700]


def native_site_query(query, site):
    """Remove web-engine syntax before sending a query to a site's own UI."""

    site = normalize_domain(site)
    text = _without_site_operators(query)
    aliases = next(
        (
            aliases for aliases, domain, _platform in KNOWN_SITE_ALIASES
            if domain_matches(site, domain)
        ),
        (),
    )
    # Search-query builders often prepend the selected website's name. It is
    # useful to a web engine but noise inside that website's own search box.
    for alias in sorted(aliases, key=len, reverse=True):
        text = re.sub(
            r"^\s*" + re.escape(alias) + r"(?:\s+|[：:，,、-]+)",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    if domain_matches(site, "bilibili.com"):
        # Bilibili's native keyword box does not need web-engine exact-phrase
        # punctuation; keeping literal quote characters can reduce its native
        # API matches for Chinese entity names.
        text = text.replace('"', "").replace("“", "").replace("”", "")
    return " ".join(text.split()).strip()[:500]
