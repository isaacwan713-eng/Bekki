# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Strict embed contracts for lazy, in-card social-video playback."""

import html
import re
from urllib.parse import parse_qs, urlencode, urlparse


_YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_BILIBILI_BVID = re.compile(r"^BV[A-Za-z0-9]{10}$", re.IGNORECASE)
WEBVIEW_WRAPPER_HOST = "bekki-video.local"
WEBVIEW_WRAPPER_ORIGIN = "https://" + WEBVIEW_WRAPPER_HOST


def _public_https_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return None
    return parsed


def social_video_contract(value):
    """Return one bounded inline-player target, or ``None`` when unsupported."""

    parsed = _public_https_url(value)
    if parsed is None:
        return None
    hostname = str(parsed.hostname or "").casefold()
    source_url = str(value or "").strip()[:2048]

    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        video_id = ""
        is_short = False
        path_parts = [part for part in parsed.path.split("/") if part]
        if hostname == "youtu.be":
            video_id = path_parts[0] if len(path_parts) == 1 else ""
        elif parsed.path.rstrip("/").casefold() == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        elif len(path_parts) == 2 and path_parts[0].casefold() in {
            "shorts", "live"
        }:
            is_short = path_parts[0].casefold() == "shorts"
            video_id = path_parts[1]
        if not _YOUTUBE_VIDEO_ID.fullmatch(video_id):
            return None
        embed_url = (
            "https://www.youtube.com/embed/"
            + video_id
            + "?"
            + urlencode({
                "autoplay": "1",
                "playsinline": "1",
                "rel": "0",
                "origin": WEBVIEW_WRAPPER_ORIGIN,
                "widget_referrer": WEBVIEW_WRAPPER_ORIGIN + "/",
            })
        )
        return {
            "platform": "youtube",
            "video_id": video_id,
            "source_url": source_url,
            "embed_url": embed_url,
            "is_short": is_short,
            "display_name": "YouTube Shorts" if is_short else "YouTube",
        }

    if hostname in {"bilibili.com", "www.bilibili.com"}:
        match = re.fullmatch(
            r"/video/(BV[A-Za-z0-9]{10})/?",
            parsed.path,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        bvid = match.group(1)
        if not _BILIBILI_BVID.fullmatch(bvid):
            return None
        embed_url = (
            "https://player.bilibili.com/player.html?"
            + urlencode({
                "bvid": bvid,
                "page": "1",
                "high_quality": "1",
                "danmaku": "0",
                "autoplay": "1",
                # Bilibili's documented external-player contract supports an
                # explicit muted flag.  Keep audio enabled after the user has
                # deliberately clicked Bekki's play button instead of relying
                # on a cached/default player mute state.
                "muted": "0",
            })
        )
        return {
            "platform": "bilibili",
            "video_id": bvid,
            "source_url": source_url,
            "embed_url": embed_url,
            "is_short": False,
            "display_name": "哔哩哔哩",
        }

    return None


def _verified_contract(contract):
    """Rebuild a player contract before placing any value into HTML."""

    if not isinstance(contract, dict):
        return None
    rebuilt = social_video_contract(contract.get("source_url"))
    if rebuilt is None:
        return None
    for key in ("platform", "video_id", "embed_url"):
        if str(rebuilt.get(key) or "") != str(contract.get(key) or ""):
            return None
    return rebuilt


def webview_wrapper_url(contract):
    """Return the exact virtual HTTPS document used inside Edge WebView2."""

    verified = _verified_contract(contract)
    if verified is None:
        return ""
    platform = str(verified.get("platform") or "")
    video_id = str(verified.get("video_id") or "")
    return f"{WEBVIEW_WRAPPER_ORIGIN}/player/{platform}/{video_id}"


def embed_document_url(contract):
    """Compatibility alias for the verified WebView2 wrapper URL."""

    return webview_wrapper_url(contract)


def embed_wrapper_html(contract):
    """Create the verified player plus Bekki's in-surface companion panel."""

    verified = _verified_contract(contract)
    if verified is None:
        return ""
    iframe_src = html.escape(str(verified["embed_url"]), quote=True)
    title = html.escape(str(verified.get("display_name") or "Video"), quote=True)
    document = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-src https://www.youtube.com https://www.youtube-nocookie.com https://player.bilibili.com">
  <style>
    :root { color-scheme: dark; font-family: "Segoe UI Variable", "Microsoft YaHei UI", sans-serif; }
    html, body { width:100%; height:100%; margin:0; overflow:hidden; background:#080b10; }
    iframe { position:absolute; inset:0; width:100%; height:100%; margin:0; border:0; background:#080b10; z-index:0; }
    #bekki-companion {
      position:absolute; right:12px; bottom:12px; z-index:20;
      display:none; flex-direction:column;
      width:min(320px, calc(100% - 24px)); max-height:min(54%, 430px);
      overflow:hidden; border:1px solid rgba(159,203,237,.58); border-radius:16px;
      background:rgba(13,24,37,.94); color:#edf7ff;
      box-shadow:0 14px 42px rgba(0,0,0,.48); backdrop-filter:blur(12px);
    }
    #bekki-companion.visible { display:flex; }
    #bekki-companion.minimized .companion-body,
    #bekki-companion.minimized .companion-form { display:none; }
    .companion-header { display:flex; align-items:center; gap:7px; padding:9px 9px 8px 12px; border-bottom:1px solid rgba(122,164,199,.22); }
    .companion-avatar { width:22px; height:22px; display:grid; place-items:center; border-radius:50%; background:#d9efff; color:#2873ad; font-size:13px; }
    .companion-title { flex:1; font-size:12px; font-weight:750; letter-spacing:.1px; }
    .companion-status { color:#8eb5d6; font-size:10px; font-weight:600; }
    .companion-icon { width:27px; height:25px; padding:0; border:0; border-radius:8px; background:rgba(121,167,205,.13); color:#c9e8ff; cursor:pointer; font:700 14px/25px inherit; }
    .companion-icon:hover { background:rgba(121,167,205,.27); }
    .companion-body { display:flex; flex-direction:column; gap:7px; min-height:72px; padding:10px; overflow:auto; scrollbar-width:thin; }
    .companion-empty { margin:auto; color:#92abc0; font-size:11px; text-align:center; }
    .companion-message { max-width:86%; padding:7px 9px; border-radius:11px; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; line-height:1.45; }
    .companion-message.bekki { align-self:flex-start; background:#20364b; color:#eef8ff; border-bottom-left-radius:4px; }
    .companion-message.you { align-self:flex-end; background:#f0d7e5; color:#402d3a; border-bottom-right-radius:4px; }
    .companion-form { display:flex; gap:7px; padding:8px; border-top:1px solid rgba(122,164,199,.22); }
    .companion-input { min-width:0; flex:1; padding:8px 10px; border:1px solid #37556f; border-radius:10px; outline:none; background:#0e1a27; color:#f1f8ff; font:12px/1.3 inherit; }
    .companion-input:focus { border-color:#74b7ea; box-shadow:0 0 0 2px rgba(91,166,239,.16); }
    .companion-input:disabled { color:#7890a4; }
    .companion-send { border:1px solid #66aae0; border-radius:10px; padding:0 11px; background:#438ec8; color:white; cursor:pointer; font:700 11px/1 inherit; }
    .companion-send:disabled { opacity:.5; cursor:default; }
    @media (max-width:520px) {
      #bekki-companion { right:8px; bottom:8px; width:min(285px, calc(100% - 16px)); max-height:48%; }
    }
  </style>
</head>
<body>
  <iframe
    id="bekki-inline-player"
    title="__TITLE__"
    src="__IFRAME_SRC__"
    referrerpolicy="strict-origin-when-cross-origin"
    allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
    allowfullscreen></iframe>
  <section id="bekki-companion" aria-label="Bekki 陪看对话">
    <header class="companion-header">
      <span class="companion-avatar" aria-hidden="true">●</span>
      <span class="companion-title">Bekki 陪看</span>
      <span id="bekki-companion-status" class="companion-status">一起看</span>
      <button id="bekki-companion-minimize" class="companion-icon" type="button" title="收起">—</button>
      <button id="bekki-companion-close" class="companion-icon" type="button" title="关闭">×</button>
    </header>
    <div id="bekki-companion-body" class="companion-body" aria-live="polite">
      <div id="bekki-companion-empty" class="companion-empty">看到什么都可以在这里问我～</div>
    </div>
    <form id="bekki-companion-form" class="companion-form">
      <input id="bekki-companion-input" class="companion-input" maxlength="320" autocomplete="off" placeholder="和 Bekki 说点什么…">
      <button id="bekki-companion-send" class="companion-send" type="submit">发送</button>
    </form>
  </section>
  <script>
    (() => {
      "use strict";
      const panel = document.getElementById("bekki-companion");
      const body = document.getElementById("bekki-companion-body");
      const empty = document.getElementById("bekki-companion-empty");
      const form = document.getElementById("bekki-companion-form");
      const input = document.getElementById("bekki-companion-input");
      const send = document.getElementById("bekki-companion-send");
      const status = document.getElementById("bekki-companion-status");
      const minimize = document.getElementById("bekki-companion-minimize");
      const close = document.getElementById("bekki-companion-close");

      function post(payload) {
        try {
          const api = window.qtwebview2 && window.qtwebview2.api;
          if (!api || typeof api.bekki_companion_event !== "function") {
            setBusy(false);
            return false;
          }
          Promise.resolve(api.bekki_companion_event(payload)).catch(() => {
            setBusy(false);
          });
          return true;
        } catch (_error) {
          setBusy(false);
          return false;
        }
      }

      function cleanText(value) {
        return String(value || "").replace(/\s+/g, " ").trim().slice(0, 320);
      }

      function addMessage(role, value) {
        const text = cleanText(value);
        if (!text) return;
        empty.hidden = true;
        const item = document.createElement("div");
        item.className = "companion-message " + (role === "YOU" ? "you" : "bekki");
        item.textContent = text;
        body.appendChild(item);
        while (body.querySelectorAll(".companion-message").length > 8) {
          const oldest = body.querySelector(".companion-message");
          if (oldest) oldest.remove();
        }
        body.scrollTop = body.scrollHeight;
      }

      function setBusy(busy) {
        const value = Boolean(busy);
        input.disabled = value;
        send.disabled = value;
        status.textContent = value ? "正在看…" : "一起看";
        if (!value && panel.classList.contains("visible") && !panel.classList.contains("minimized")) {
          input.focus({preventScroll:true});
        }
      }

      window.BekkiCompanion = Object.freeze({
        setEnabled(enabled) {
          panel.classList.toggle("visible", Boolean(enabled));
          if (enabled) {
            panel.classList.remove("minimized");
            setTimeout(() => input.focus({preventScroll:true}), 0);
          } else {
            setBusy(false);
          }
        },
        setBusy,
        addMessage,
        reset() {
          body.querySelectorAll(".companion-message").forEach((item) => item.remove());
          empty.hidden = false;
          input.value = "";
          setBusy(false);
        }
      });

      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const text = cleanText(input.value);
        if (!text || input.disabled) return;
        input.value = "";
        addMessage("YOU", text);
        setBusy(true);
        post({type:"companion_message", text});
      });
      minimize.addEventListener("click", () => {
        const collapsed = panel.classList.toggle("minimized");
        minimize.textContent = collapsed ? "+" : "—";
        minimize.title = collapsed ? "展开" : "收起";
      });
      close.addEventListener("click", () => {
        panel.classList.remove("visible");
        setBusy(false);
        post({type:"companion_close"});
      });
    })();
  </script>
</body>
</html>"""
    return document.replace("__TITLE__", title).replace(
        "__IFRAME_SRC__",
        iframe_src,
    )


def webview_wsgi_app(contract):
    """Serve one verified wrapper document through WebView2's virtual host."""

    verified = _verified_contract(contract)
    wrapper_url = webview_wrapper_url(verified)
    wrapper_html = embed_wrapper_html(verified)
    if verified is None or not wrapper_url or not wrapper_html:
        return None
    wrapper_path = urlparse(wrapper_url).path
    wrapper_bytes = wrapper_html.encode("utf-8")

    def application(environ, start_response):
        method = str(environ.get("REQUEST_METHOD") or "GET").upper()
        scheme = str(environ.get("wsgi.url_scheme") or "").casefold()
        server_name = str(environ.get("SERVER_NAME") or "").casefold()
        path = str(environ.get("PATH_INFO") or "")
        query = str(environ.get("QUERY_STRING") or "")
        allowed = (
            method in {"GET", "HEAD"}
            and scheme == "https"
            and server_name == WEBVIEW_WRAPPER_HOST
            and path == wrapper_path
            and not query
        )
        if not allowed:
            body = b"Not Found"
            start_response(
                "404 Not Found",
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-store"),
                    ("X-Content-Type-Options", "nosniff"),
                ],
            )
            return [] if method == "HEAD" else [body]
        headers = [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(wrapper_bytes))),
            ("Cache-Control", "no-store, max-age=0"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("X-Content-Type-Options", "nosniff"),
        ]
        start_response("200 OK", headers)
        return [] if method == "HEAD" else [wrapper_bytes]

    return application


def allowed_webview_navigation(value, contract):
    """Keep top-level WebView2 navigation bound to one verified player."""

    if str(value or "").strip().casefold() == "about:blank":
        return True
    verified = _verified_contract(contract)
    if verified is None:
        return False
    candidate = str(value or "").strip()
    if candidate == webview_wrapper_url(verified):
        return True
    if candidate == str(verified.get("embed_url") or ""):
        return True
    return False


def allowed_embed_navigation(value, contract):
    """Compatibility alias for callers using the V1.10.43 function name."""

    if allowed_webview_navigation(value, contract):
        return True
    if not isinstance(contract, dict):
        return False
    parsed = _public_https_url(value)
    if parsed is None:
        return False
    hostname = str(parsed.hostname or "").casefold()
    video_id = str(contract.get("video_id") or "")
    platform = str(contract.get("platform") or "").casefold()
    if platform == "youtube":
        return (
            hostname in {
                "youtube-nocookie.com",
                "www.youtube-nocookie.com",
                "youtube.com",
                "www.youtube.com",
            }
            and parsed.path.rstrip("/") == "/embed/" + video_id
        )
    if platform == "bilibili":
        return (
            hostname == "player.bilibili.com"
            and parsed.path.rstrip("/") == "/player.html"
            and parse_qs(parsed.query).get("bvid", [""])[0].casefold()
            == video_id.casefold()
        )
    return False
