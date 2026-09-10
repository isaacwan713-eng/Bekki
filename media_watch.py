# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Closed contracts for Bekki's watch-search and theater follow-ups."""

import re
from urllib.parse import urlparse


KNOWN_SITE_ALIASES = (
    (("bilibili", "b站", "哔哩哔哩"), "bilibili.com"),
    (("youtube", "油管"), "youtube.com"),
    (("crunchyroll",), "crunchyroll.com"),
    (("netflix", "奈飞"), "netflix.com"),
    (("hulu",), "hulu.com"),
    (("disney+", "disney plus", "迪士尼+"), "disneyplus.com"),
    (("prime video", "amazon prime video"), "primevideo.com"),
    (("爱奇艺", "iqiyi"), "iq.com"),
    (("腾讯视频",), "v.qq.com"),
    (("优酷", "youku"), "youku.com"),
    (("芒果tv", "芒果 tv", "mgtv"), "mgtv.com"),
)

DEFAULT_WATCH_SITES = (
    "bilibili.com",
    "youtube.com",
    "crunchyroll.com",
)

ALLOWED_WATCH_SITES = frozenset(
    {
        domain
        for _aliases, domain in KNOWN_SITE_ALIASES
    }
    | {
        "youtu.be",
        "amazon.com",
        "iqiyi.com",
    }
)

RANDOM_MARKERS = (
    "随机",
    "随便",
    "来一个",
    "来个",
    "找一个",
    "找个",
    "看一个",
    "看个",
    "放一个",
    "放个",
    "挑一个",
    "挑个",
    "来点",
    "换一个",
    "换个",
    "another",
    "random",
    "surprise me",
)

WATCH_MARKERS = (
    "想看",
    "要看",
    "播放",
    "放一个",
    "放个",
    "找一个",
    "找个",
    "找来看看",
    "watch",
    "play",
)

_PLAYBACK_CONTROL_PREFIX = re.compile(
    r"^\s*(?:(?:请|麻烦|帮我|给我|把|将|现在|先|再|让它|让视频|这个视频|视频)\s*)*"
    r"(?:暂停|继续(?:播放|看)?|恢复(?:播放)?|停止(?:播放)?|静音|取消静音|"
    r"调(?:高|低|大|小)(?:音量|声音)?|声音(?:大|小)一点|音量(?:大|小)一点|"
    r"快进|快退|倒退|跳到|倍速|全屏|退出全屏|上一集|下一集)",
    flags=re.IGNORECASE,
)

_GENERIC_WATCH_TOPICS = {
    "这个",
    "那个",
    "它",
    "当前",
    "现在这个",
    "这个视频",
    "那个视频",
    "当前视频",
    "正在看的视频",
    "下一集",
    "上一集",
    "下一个",
    "上一个",
    "视频",
    "影片",
    "节目",
    "内容",
    "this",
    "that",
    "it",
    "this video",
    "that video",
    "the video",
    "video",
}

_MEDIA_CONTEXT_MARKERS = (
    "视频",
    "短片",
    "电影",
    "电视剧",
    "剧集",
    "动漫",
    "动画",
    "纪录片",
    "综艺",
    "直播",
    "比赛",
    "演唱会",
    "mv",
    "shorts",
    "video",
    "movie",
    "episode",
    "series",
    "show",
)

_RESEARCH_REQUEST_MARKERS = (
    "搜索",
    "搜一下",
    "搜一搜",
    "检索",
    "总结",
    "分析",
    "评价",
    "评论",
    "讨论",
    "观点",
    "帖子",
    "动态",
    "新闻",
    "资料",
    "讲了什么",
    "search for posts",
    "summarize",
    "research",
)


def _compact(value, limit=240):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def normalize_site(value):
    """Return one public hostname suitable for a search ``site:`` condition."""

    raw = _compact(value, 200).casefold()
    if not raw:
        return ""
    if "://" in raw:
        try:
            raw = str(urlparse(raw).hostname or "").casefold()
        except ValueError:
            return ""
    elif "/" in raw:
        try:
            raw = str(urlparse("https://" + raw).hostname or "").casefold()
        except ValueError:
            return ""
    raw = raw.removeprefix("www.").strip(" ./")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", raw):
        return ""
    if "." not in raw or ".." in raw:
        return ""
    blocked = (
        raw == "localhost"
        or raw.endswith((".localhost", ".local", ".internal"))
        or re.fullmatch(r"\d+(?:\.\d+){3}", raw) is not None
    )
    return "" if blocked else raw


def extract_requested_sites(message):
    """Extract only sites literally named by the user; never invent a condition."""

    text = _compact(message, 1600).casefold()
    sites = []

    def add(value):
        site = normalize_site(value)
        if site and site not in sites:
            sites.append(site)

    for aliases, domain in KNOWN_SITE_ALIASES:
        if any(alias.casefold() in text for alias in aliases):
            add(domain)
    for match in re.findall(
        r"(?:https?://)?(?:www\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\.[a-z]{2,}"
        r"(?:/[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?",
        text,
        flags=re.IGNORECASE,
    ):
        add(match)
    # A previously verified video site can later be addressed by the site name
    # Bekki learned from its public page (for example “爱壹帆” after iyf.tv was
    # structurally verified). Unverified user wording never creates a site.
    try:
        import video_sites

        for learned in video_sites.match_aliases(text):
            add(learned)
    except (ImportError, OSError, ValueError):
        pass
    return sites[:4]


def selection_mode(message):
    text = _compact(message, 1200).casefold()
    return "RANDOM_ONE" if any(marker in text for marker in RANDOM_MARKERS) else "EXACT"


def looks_like_watch_request(message):
    text = _compact(message, 1200).casefold()
    if not text:
        return False
    return any(marker in text for marker in WATCH_MARKERS)


def looks_like_media_discovery_request(message):
    """Separate finding media from controlling an already-active player.

    This is a narrow routing contract, not a general intent classifier.  It
    only repairs a lane when the user supplies both a watch/find verb and a
    concrete media subject (or a random category).  Pause, resume, volume,
    seek, fullscreen and episode controls remain device/application actions.
    """

    text = _compact(message, 1200)
    if not text:
        return False
    requested_sites = extract_requested_sites(text)
    intent_text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    lowered = intent_text.casefold()
    if any(marker in lowered for marker in _RESEARCH_REQUEST_MARKERS):
        return False
    chinese_intent = any(
        marker in lowered
        for marker in WATCH_MARKERS + RANDOM_MARKERS
        if re.search(r"[\u3400-\u9fff]", marker)
    )
    english_watch = re.search(r"\bwatch\b", lowered) is not None
    english_play = re.search(r"\bplay\b", lowered) is not None
    english_discovery = re.search(r"\b(?:find|pick)\b", lowered) is not None
    english_intent = english_watch or english_play or english_discovery
    site_view_intent = bool(requested_sites) and re.search(
        r"(?:^|\s|去|在|从)(?:[^。！？!?]{0,80})(?:看|观看)",
        lowered,
    ) is not None
    if not chinese_intent and not english_intent and not site_view_intent:
        return False
    if _PLAYBACK_CONTROL_PREFIX.search(lowered) or re.search(
        r"^\s*(?:please\s+)?(?:pause|resume|unpause|stop|mute|unmute|"
        r"seek|fullscreen|exit fullscreen|next episode|previous episode)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False
    topic = _compact(fallback_topic(text, requested_sites), 180).casefold()
    topic = re.sub(r"\s+", " ", topic).strip(" .。!！?？")
    if not topic or topic in _GENERIC_WATCH_TOPICS:
        return False
    if re.fullmatch(
        r"(?:到\s*)?(?:第\s*)?\d+\s*(?:集|话|期|episode)?",
        topic,
        flags=re.IGNORECASE,
    ):
        return False
    has_media_context = any(marker in lowered for marker in _MEDIA_CONTEXT_MARKERS)
    explicit_playback = (
        "播放" in lowered
        or "放一个" in lowered
        or "放个" in lowered
        or english_watch
        or (english_play and (bool(requested_sites) or has_media_context))
    )
    quoted_title = re.search(r"《[^》]{2,120}》", text) is not None
    has_random_selection = any(
        marker in lowered for marker in RANDOM_MARKERS
    )
    if not (
        explicit_playback
        or quoted_title
        or site_view_intent
        or (has_random_selection and has_media_context)
        or (english_discovery and has_media_context)
    ):
        return False
    return len(re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", topic)) >= 2


def fallback_topic(message, requested_sites=None):
    """Strip action/site scaffolding while retaining the requested media subject."""

    text = _compact(message, 500)
    for aliases, _domain in KNOWN_SITE_ALIASES:
        for alias in aliases:
            text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)
    for site in requested_sites or []:
        text = re.sub(
            r"(?:https?://)?(?:www\.)?"
            + re.escape(str(site))
            + r"(?:/[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?",
            " ",
            text,
            flags=re.IGNORECASE,
        )
    # Once a site has been structurally verified, its learned display name is
    # also request scaffolding (for example “去爱壹帆看名侦探柯南”).  Reading an
    # alias never verifies a site and never creates a registry entry.
    try:
        import video_sites

        for site in requested_sites or []:
            learned = video_sites.get_site(site)
            if not (learned or {}).get("verified"):
                continue
            for alias in learned.get("aliases", []):
                text = re.sub(re.escape(alias), " ", text, flags=re.IGNORECASE)
    except (ImportError, OSError, ValueError):
        pass
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    # Remove longer intent phrases before their component words.  This keeps
    # the deterministic fallback clean for examples such as “去 B 站找一个
    # 下饭视频” even when the local extraction model is unavailable.
    scaffolding = (
        r"(?:我现在想要看|我现在想看|我想要看|我想看|想要看|想看|要看|看看)",
        r"(?:帮我|给我|麻烦|请|现在我|我现在|现在)",
        r"^\s*(?:我\s*)?(?:去|在|从)\s*",
        r"(?:网上|网站|平台|里面|上面)",
        r"(?:随机|随便|来一个|来个|来点|找一个|找个|看一个|看个|放一个|放个|挑一个|挑个)",
        r"^\s*(?:一个|个)\s*",
        r"(?:搜索一下|搜一下|搜索|搜|寻找|找一下|找|挑选|挑|播放|观看|看|放)",
        r"(?:可以吗|好吗|吧|一下|一个)$",
    )
    for pattern in scaffolding:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[《》“”\"'：:，,。！？!?()（）]+", " ", text)
    topic = _compact(text, 180)
    return topic or "视频"


def domain_matches_site(domain, site):
    host = normalize_site(domain)
    target = normalize_site(site)
    return bool(host and target and (host == target or host.endswith("." + target)))


def is_builtin_video_site(site):
    """Return whether Bekki ships with an explicit video-site contract."""

    normalized = normalize_site(site)
    return any(
        domain_matches_site(normalized, known)
        or domain_matches_site(known, normalized)
        for known in ALLOWED_WATCH_SITES
    )


def site_label(site):
    site = normalize_site(site)
    labels = {
        "bilibili.com": "B 站",
        "youtube.com": "YouTube",
        "crunchyroll.com": "Crunchyroll",
        "netflix.com": "Netflix",
        "hulu.com": "Hulu",
        "disneyplus.com": "Disney+",
        "primevideo.com": "Prime Video",
        "iq.com": "爱奇艺",
        "v.qq.com": "腾讯视频",
        "youku.com": "优酷",
        "mgtv.com": "芒果 TV",
    }
    if site in labels:
        return labels[site]
    try:
        import video_sites

        learned = video_sites.get_site(site)
        aliases = list((learned or {}).get("aliases", []))
        if aliases:
            aliases.sort(
                key=lambda value: (
                    bool(re.search(r"[\u3400-\u9fff]", value)),
                    len(value),
                ),
                reverse=True,
            )
            return aliases[0]
    except (ImportError, OSError, ValueError):
        pass
    return site


def classify_followup(message):
    """Classify only the bounded reply to a watch-search theater question."""

    text = _compact(message, 200).casefold()
    normalized = re.sub(r"[\s，,。.!！?？]+", "", text)
    if any(token in normalized for token in ("换一个", "换个", "下一个", "再来一个", "再来个", "another")):
        return "NEXT"
    if normalized in {
        "可以", "好", "好的", "行", "进入", "进入影院", "进入影院模式",
        "播放", "开始播放", "yes", "ok", "okay", "play",
    }:
        return "ENTER_THEATER"
    if normalized in {
        "不用", "不用了", "取消", "不看了", "算了", "no", "cancel",
    }:
        return "CANCEL"
    return "NEW_REQUEST"
