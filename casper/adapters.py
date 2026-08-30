"""Compatibility adapters between Casper and Bekki's stable V1/V2 tools."""

import json
import os
import re
import subprocess


def _render_listed_folder(action_result):
    """Render trusted structured folder evidence without generative rewriting."""
    folder = str(action_result.get("folder") or "文件夹")
    items = action_result.get("items")
    if not isinstance(items, list):
        items = []
    if not items:
        return folder + " 文件夹目前是空的。"
    lines = [folder + " 文件夹里有 " + str(len(items)) + " 项："]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = "文件夹" if item.get("kind") == "folder" else "文件"
        lines.append("- " + name + "（" + kind + "）")
    return "\n".join(lines)


def _render_file_search(action_result):
    """Render only filesystem matches observed by the bounded executor."""
    query = str(action_result.get("query") or "目标").strip()
    matches = action_result.get("matches")
    if not isinstance(matches, list):
        matches = []
    scope = action_result.get("scope")
    if not isinstance(scope, list):
        scope = []
    scope_text = "、".join(str(item) for item in scope if str(item).strip())
    if not matches:
        prefix = "在 " + scope_text + " 中" if scope_text else "在已搜索范围内"
        if action_result.get("truncated"):
            return prefix + "暂未找到 “" + query + "”；搜索达到安全上限。"
        return prefix + "没有找到 “" + query + "”。"

    lines = ["找到 " + str(len(matches)) + " 个匹配项："]
    for item in matches:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            lines.append("- " + path)
    if action_result.get("truncated"):
        lines.append("- 搜索达到安全上限，仅显示以上结果")
    return "\n".join(lines)


def _render_recycle_bin(action_result):
    """Render trusted read-only Recycle Bin evidence exactly once."""
    items = action_result.get("items")
    if not isinstance(items, list):
        items = []
    if not items:
        return "回收站目前是空的。"
    lines = ["回收站里有 " + str(len(items)) + " 项："]
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        details = []
        location = str(item.get("original_location") or "").strip()
        deleted = str(item.get("date_deleted") or "").strip()
        if location:
            details.append("原位置：" + location)
        if deleted:
            details.append("删除时间：" + deleted)
        suffix = "（" + "；".join(details) + "）" if details else ""
        lines.append("- " + name + suffix)
    if action_result.get("truncated"):
        lines.append("- 仅显示前 100 项")
    return "\n".join(lines)


def _render_window_control(action_result):
    window = str(action_result.get("window") or "所选窗口")
    control = str(action_result.get("control") or "")
    verbs = {
        "FOCUS_WINDOW": "已切换到",
        "MINIMIZE_WINDOW": "已最小化",
        "MAXIMIZE_WINDOW": "已最大化",
        "RESTORE_WINDOW": "已还原",
    }
    return verbs.get(control, "已操作") + " " + window + "。"


def _render_steam_library(action_result):
    """Render the read-only installed Steam manifest inventory."""
    games = action_result.get("items")
    if not isinstance(games, list):
        games = []
    total = int(action_result.get("total_count") or len(games))
    if not games:
        return "本机没有发现已安装的 Steam 游戏。"
    lines = ["本机 Steam 库检测到 " + str(total) + " 个已安装游戏："]
    for game in games:
        name = str(game.get("name") if isinstance(game, dict) else game).strip()
        if name:
            lines.append("- " + name)
    if action_result.get("truncated"):
        lines.append("- 仅显示前 " + str(len(games)) + " 个")
    return "\n".join(lines)


def _simple_application_target(message):
    """Extract only an explicit bounded open/launch application command."""
    text = str(message or "").strip()
    patterns = (
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:打开|启动|运行)\s*(.+?)\s*[。.!！]?$",
        r"^(?:please\s+)?(?:open|launch|start|run)\s+(.+?)\s*[.!]?$",
    )
    target = ""
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            target = match.group(1).strip(" \t\"'“”‘’")
            break
    target = re.sub(
        r"\s*(?:应用|程序|客户端|app|application|client)$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    if not target or len(target) > 100:
        return ""
    blocked = (
        "回收站", "文件夹", "目录", "窗口", "网页", "网站", "链接",
        "recycle bin", "folder", "directory", "window", "website", "url",
    )
    lowered = target.casefold()
    if any(value in lowered for value in blocked):
        return ""
    return target


def _application_key(value):
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value).casefold())


def _is_genshin_target(target):
    return _application_key(target) in {
        _application_key("原神"),
        _application_key("Genshin"),
        _application_key("Genshin Impact"),
    }


def _run_hoyoplay_genshin_ui():
    from . import hoyoplay

    return hoyoplay.launch_genshin_via_ui()


def _launch_genshin_through_hoyoplay():
    """Open learned HoYoPlay, then launch only a UI-confirmed Genshin page."""
    launcher = _launch_start_menu_application("HoYoPlay")
    if not isinstance(launcher, dict) or not launcher.get("success"):
        return {
            "success": False,
            "completed": False,
            "needs_clarification": True,
            "action": "launcher_not_found",
            "application": "HoYoPlay",
            "game": "Genshin Impact",
            "clarification": "没有找到或无法启动已安装的 HoYoPlay。",
            "reason": "The required local launcher could not be opened.",
        }
    ui_result = _run_hoyoplay_genshin_ui()
    status = str(ui_result.get("status") or "automation_error")
    base = {
        "application": "HoYoPlay",
        "game": "Genshin Impact",
        "launch_route": str(
            ui_result.get("route") or "hoyoplay_ui_automation"
        ),
        "skill_state": str(launcher.get("skill_state") or "reused"),
        "launcher_window": str(ui_result.get("window") or "HoYoPlay"),
        "launch_control": str(ui_result.get("control") or ""),
    }
    if status == "game_opened":
        return {
            **base,
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "game_opened",
            "reason": "Verified the Genshin process after HoYoPlay launch.",
        }
    if status == "launch_dispatched":
        return {
            **base,
            "success": False,
            "completed": False,
            "needs_clarification": True,
            "action": "game_launch_unverified",
            "clarification": (
                "已在 HoYoPlay 中发送启动点击，但没有检测到原神进程，"
                "因此不能确认游戏已经开始。"
            ),
            "reason": (
                "Invoked the Genshin launch control in HoYoPlay; the game "
                "process was not visible before the verification timeout."
            ),
        }
    clarifications = {
        "launcher_not_ready": "HoYoPlay 已启动，但窗口还没有准备好。",
        "game_identity_not_visible": (
            "HoYoPlay 已打开，但没有在窗口中确认到原神页面，因此没有点击。"
        ),
        "launch_control_not_found": (
            "已确认 HoYoPlay 中的原神页面，但没有找到可用的“开始游戏”按钮。"
        ),
        "launch_control_unavailable": (
            "找到了原神的“开始游戏”按钮，但 Windows 无法安全调用它。"
        ),
        "vision_window_unavailable": (
            "HoYoPlay 已启动，但无法取得可截图的前台窗口。"
        ),
        "vision_capture_failed": "HoYoPlay 已启动，但窗口截图失败。",
        "vision_model_unavailable": (
            "HoYoPlay 已打开，但本地视觉模型启动失败（Ollama/CUDA），"
            "因此没有点击。请重启 Ollama 后再试。"
        ),
        "vision_output_invalid": (
            "HoYoPlay 已打开，但视觉模型没有返回可验证的定位结果，"
            "因此没有点击。"
        ),
        "vision_target_unverified": (
            "HoYoPlay 已打开，但视觉模型没有同时确认原神页面和启动按钮，"
            "因此没有点击。"
        ),
        "vision_click_failed": (
            "视觉模型确认了原神启动按钮，但 Windows 没有完成安全点击。"
        ),
    }
    return {
        **base,
        "success": False,
        "completed": False,
        "needs_clarification": True,
        "action": status,
        "clarification": clarifications.get(
            status,
            "HoYoPlay 已打开，但自动启动原神的操作没有完成。",
        ),
        "reason": str(ui_result.get("reason") or status),
    }


def _steam_game_target(message):
    """Extract a game name only from an explicit Steam launch command."""
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    patterns = (
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:打开|启动|运行)\s*steam\s*(?:里|中的|上)?\s*(?:的)?\s*(?:游戏)?\s*(.+?)\s*[。.!！]?$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*用\s*steam\s*(?:打开|启动|运行)\s*(.+?)\s*[。.!！]?$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*在\s*steam\s*(?:里|中|上)?\s*(?:打开|启动|运行)\s*(.+?)\s*[。.!！]?$",
        r"^(?:please\s+)?(?:open|launch|start|run)\s+(.+?)\s+(?:in|with|through)\s+steam\s*[.!]?$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            target = match.group(1).strip(" \t\"'“”‘’")
            if target and len(target) <= 160:
                return target
    return ""


def _is_steam_library_list_request(message):
    """Recognize an explicit request to list locally installed Steam games."""
    text = re.sub(r"\s+", " ", str(message or "")).strip()
    patterns = (
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:看看|看一下|查看|列出|显示)\s*(?:我的)?\s*steam\s*(?:游戏)?库\s*(?:里|中)?\s*(?:有|装了|安装了)?\s*(?:什么|哪些)?\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:请|麻烦)?\s*(?:帮我)?\s*(?:看看|看一下|查看|列出|显示)\s*steam\s*(?:里|中|上)?\s*(?:有|装了|安装了)\s*(?:什么|哪些)\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:我的)?\s*steam\s*(?:游戏)?库\s*(?:里|中)?\s*(?:有|装了|安装了)\s*(?:什么|哪些)\s*(?:游戏)?\s*[？?。.!！]?$",
        r"^(?:please\s+)?(?:show|list|display)\s+(?:me\s+)?(?:my\s+)?installed\s+steam\s+games\s*[.!]?$",
        r"^(?:what(?:'s| is)\s+in\s+my\s+steam\s+library|which\s+steam\s+games\s+are\s+installed)\s*[?!.]?$",
    )
    return any(re.match(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _list_installed_steam_games(limit=100):
    """Return a bounded read-only inventory from installed Steam manifests."""
    from . import application_skills

    games = application_skills.discover_steam_games()
    total = len(games)
    visible = [
        {"name": str(game.get("name") or "").strip()}
        for game in games[:limit]
        if isinstance(game, dict) and str(game.get("name") or "").strip()
    ]
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "listed_steam_library",
        "application": "Steam",
        "items": visible,
        "total_count": total,
        "truncated": total > len(visible),
        "reason": "Read installed Steam app manifests without modifying them.",
    }


def _find_exact_start_menu_shortcut(target):
    """Return one exact Start-menu shortcut without fuzzy substitution."""
    if os.name != "nt":
        return ""
    roots = []
    appdata = str(os.environ.get("APPDATA") or "").strip()
    programdata = str(os.environ.get("ProgramData") or "").strip()
    if appdata:
        roots.append(
            os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")
        )
    if programdata:
        roots.append(
            os.path.join(
                programdata, "Microsoft", "Windows", "Start Menu", "Programs"
            )
        )
    requested_key = _application_key(target)
    matches = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for directory, _folders, files in os.walk(root):
                for filename in files:
                    stem, extension = os.path.splitext(filename)
                    if extension.casefold() != ".lnk":
                        continue
                    if _application_key(stem) == requested_key:
                        matches.append(os.path.join(directory, filename))
        except OSError:
            continue
    unique = []
    seen = set()
    for match in matches:
        key = os.path.normcase(os.path.abspath(match))
        if key not in seen:
            seen.add(key)
            unique.append(match)
    return unique[0] if unique else ""


def _launch_exact_start_menu_shortcut(shortcut_path):
    """Launch a previously resolved exact .lnk through Windows Explorer."""
    path = str(shortcut_path or "").strip()
    if os.name != "nt" or not path:
        return False
    try:
        launched = subprocess.run(
            ["explorer.exe", path],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # Explorer commonly returns 1 after successfully delegating a shell item.
    return launched.returncode in {0, 1}


def _launch_apps_folder_id(app_id):
    """Launch one already-resolved exact AppsFolder identity."""
    identity = str(app_id or "").strip()
    if os.name != "nt" or not identity:
        return False
    try:
        launched = subprocess.run(
            ["explorer.exe", "shell:AppsFolder\\" + identity],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    # Explorer commonly returns 1 after successfully delegating AppsFolder.
    return launched.returncode in {0, 1}


def _dispatch_steam_game(app_id):
    """Send one validated numeric Steam AppID to the Windows shell."""
    game_id = str(app_id or "").strip()
    if os.name != "nt" or not game_id.isdigit():
        return False
    try:
        launched = subprocess.run(
            ["explorer.exe", "steam://rungameid/" + game_id],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return launched.returncode in {0, 1}


def _launch_steam_game(target):
    """Resolve and dispatch one locally installed Steam game."""
    if os.name != "nt":
        return None
    from . import application_skills

    learned = application_skills.get_steam_game(target)
    if isinstance(learned, dict):
        learned_id = str(learned.get("app_id") or "").strip()
        learned_name = str(learned.get("name") or target).strip()
        if _dispatch_steam_game(learned_id):
            application_skills.remember_steam_game(
                target,
                name=learned_name,
                app_id=learned_id,
                launch_route="learned_steam_game",
            )
            return {
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "game_launch_dispatched",
                "application": "Steam",
                "game": learned_name,
                "steam_app_id": learned_id,
                "launch_route": "learned_steam_game",
                "skill_state": "reused",
                "reason": "Reused a learned installed Steam game identity.",
            }

    games = application_skills.discover_steam_games()
    requested_key = _application_key(target)
    exact = [
        game for game in games
        if _application_key(game.get("name")) == requested_key
    ]
    selected = exact[0] if len(exact) == 1 else None
    if selected is None:
        selected = application_skills.select_installed_candidate(
            target,
            games,
            "steam_game",
        )
    if not isinstance(selected, dict):
        return None
    game_id = str(selected.get("app_id") or "").strip()
    game_name = str(selected.get("name") or target).strip()
    if not game_id.isdigit() or not _dispatch_steam_game(game_id):
        return None
    application_skills.remember_steam_game(
        target,
        name=game_name,
        app_id=game_id,
        launch_route="steam_manifest",
    )
    return {
        "success": True,
        "completed": True,
        "needs_clarification": False,
        "action": "game_launch_dispatched",
        "application": "Steam",
        "game": game_name,
        "steam_app_id": game_id,
        "launch_route": "steam_manifest",
        "skill_state": "learned",
        "reason": "Dispatched an installed Steam manifest identity.",
    }


def _launch_start_menu_application(target):
    """Open an exact Windows Start-menu application without model guessing."""
    if os.name != "nt":
        return None
    from . import application_skills

    learned = application_skills.get_application(target)
    if isinstance(learned, dict):
        learned_name = str(learned.get("name") or target).strip()
        learned_app_id = str(learned.get("app_id") or "").strip()
        learned_shortcut = str(learned.get("shortcut_path") or "").strip()
        if learned_app_id and _launch_apps_folder_id(learned_app_id):
            application_skills.remember_application(
                target,
                name=learned_name,
                app_id=learned_app_id,
                shortcut_path=learned_shortcut,
                launch_route="learned_app_id",
            )
            return {
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "application_opened",
                "application": learned_name,
                "launch_route": "learned_app_id",
                "skill_state": "reused",
                "reason": "Reused a learned exact application identity.",
            }
        if learned_shortcut and _launch_exact_start_menu_shortcut(
            learned_shortcut
        ):
            application_skills.remember_application(
                target,
                name=learned_name,
                app_id=learned_app_id,
                shortcut_path=learned_shortcut,
                launch_route="learned_shortcut",
            )
            return {
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "application_opened",
                "application": learned_name,
                "launch_route": "learned_shortcut",
                "skill_state": "reused",
                "reason": "Reused a learned exact Start-menu shortcut.",
            }

    apps = []
    try:
        listing = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        listing = None
    if listing is not None and listing.returncode == 0 and listing.stdout.strip():
        try:
            apps = json.loads(listing.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            apps = []
    if isinstance(apps, dict):
        apps = [apps]
    if not isinstance(apps, list):
        apps = []
    requested_key = _application_key(target)
    launchable_apps = [
        {
            "name": str(app.get("Name") or "").strip(),
            "app_id": str(app.get("AppID") or "").strip(),
        }
        for app in apps
        if isinstance(app, dict)
        and str(app.get("Name") or "").strip()
        and str(app.get("AppID") or "").strip()
        and not re.match(
            r"^https?://",
            str(app.get("AppID") or "").strip(),
            flags=re.IGNORECASE,
        )
    ]
    exact = [
        app for app in launchable_apps
        if _application_key(app.get("name")) == requested_key
    ]
    selected_by_ai = False
    if len(exact) != 1:
        selected = application_skills.select_installed_candidate(
            target,
            launchable_apps,
            "application",
        )
        if isinstance(selected, dict):
            exact = [selected]
            selected_by_ai = True
    if len(exact) == 1:
        name = str(exact[0].get("name") or target).strip()
        app_id = str(exact[0].get("app_id") or "").strip()
        if _launch_apps_folder_id(app_id):
            shortcut = _find_exact_start_menu_shortcut(name)
            application_skills.remember_application(
                target,
                name=name,
                app_id=app_id,
                shortcut_path=shortcut,
                launch_route="apps_folder",
            )
            return {
                "success": True,
                "completed": True,
                "needs_clarification": False,
                "action": "application_opened",
                "application": name,
                "launch_route": "apps_folder",
                "skill_state": "learned",
                "match_route": "ai_candidate" if selected_by_ai else "exact",
                "reason": "Launched one verified Start-menu application ID.",
            }

    shortcut_name = (
        str(exact[0].get("name") or target).strip()
        if len(exact) == 1 else target
    )
    shortcut = _find_exact_start_menu_shortcut(shortcut_name)
    if shortcut and _launch_exact_start_menu_shortcut(shortcut):
        canonical_name = (
            str(exact[0].get("name") or target).strip()
            if len(exact) == 1 else str(target).strip()
        )
        discovered_app_id = (
            str(exact[0].get("app_id") or "").strip()
            if len(exact) == 1 else ""
        )
        application_skills.remember_application(
            target,
            name=canonical_name,
            app_id=discovered_app_id,
            shortcut_path=shortcut,
            launch_route="start_menu_shortcut",
        )
        return {
            "success": True,
            "completed": True,
            "needs_clarification": False,
            "action": "application_opened",
            "application": canonical_name,
            "launch_route": "start_menu_shortcut",
            "skill_state": "learned",
            "reason": "Launched the exact Start-menu shortcut.",
        }
    return None


def execute_mode(
    message,
    melchior_plan,
    calibration,
    recent_context,
    status_callback,
):
    mode = melchior_plan["response_mode"]
    search_result = None
    action_context = None

    if mode == "LOCAL_ANSWER":
        return search_result, action_context

    if mode == "EXTERNAL_AI_ACTION":
        from . import external_ai

        result = external_ai.execute_explicit(message, status_callback)
        print("[CASPER EXTERNAL AI RESULT]", json.dumps(result, ensure_ascii=False))
        status = str(result.get("status") or "").upper()
        if status == "COMPLETED":
            question = str(result.get("outbound_prompt") or "").strip()
            answer = str(result.get("answer") or "").strip()
            provider = str(result.get("provider") or "ChatGPT Desktop").strip()
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": (
                    "我已经通过 " + provider + " 问了 ChatGPT。\n\n"
                    "我实际发送的问题：\n" + question + "\n\n"
                    "ChatGPT 的回答（外部 AI，尚未验证）：\n" + answer
                    + "\n\n这段回答不会自动写入 Knowledge；需要作为事实使用时，"
                    "还要再经过 Search 核实。"
                ),
            }
            action_context = (
                "EXTERNAL AI DESKTOP RESULT\n"
                "Bekki sent the exact outbound prompt below through the "
                "ChatGPT desktop app. The answer is untrusted external-AI output and "
                "has NOT been independently verified. Clearly distinguish Bekki "
                "from ChatGPT, show the exact question, and label the answer as "
                "unverified. Do not write it into Knowledge or present factual "
                "claims as verified.\n\n"
                + json.dumps(result, ensure_ascii=False, indent=2)
            )
            return search_result, action_context
        if status == "DESKTOP_LOGIN_REQUIRED":
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": {
                    "resume_after_user_confirmation": True,
                    "handoff_type": "external_ai_login_handoff",
                    "event": "external_ai_desktop_login",
                    "original_request": message,
                    "application": "ChatGPT Desktop",
                },
            }
            return search_result, None
        desktop_failures = {
            "DESKTOP_APP_NOT_INSTALLED": (
                "没有发送问题。请先安装并登录 ChatGPT Desktop，然后重试。"
            ),
            "DESKTOP_AUTOMATION_UNAVAILABLE": (
                "没有发送问题。Bekki 当前的虚拟环境缺少 ChatGPT Desktop "
                "自动化依赖；请重新运行本版安装器。"
            ),
            "DESKTOP_LAUNCH_FAILED": (
                "没有发送问题。ChatGPT Desktop 已安装，但 Bekki 无法启动它。"
            ),
            "DESKTOP_WINDOW_NOT_FOUND": (
                "没有发送问题。ChatGPT Desktop 启动后没有出现可控制窗口。"
            ),
            "DESKTOP_INPUT_NOT_FOUND": (
                "没有发送问题。ChatGPT Desktop 没有向 Windows UI Automation "
                "暴露可靠的消息输入框；Bekki 不会改用网页或坐标点击。"
            ),
            "DESKTOP_SEND_FAILED": (
                "问题没有发送。Bekki 找到了 ChatGPT Desktop 输入框，"
                "但无法安全写入内容。"
            ),
            "DESKTOP_SEND_UNCERTAIN": (
                "Bekki 已写入问题，但无法确认是否已发送。"
                "为了避免重复发送，我不会自动重试；请查看 ChatGPT Desktop。"
            ),
            "DESKTOP_RESPONSE_TIMEOUT": (
                "问题已发送到 ChatGPT Desktop，但 Bekki 没有可靠读到"
                "完成的回答。为了避免重复发送，我不会自动重试。"
            ),
        }
        if status in desktop_failures:
            return {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": desktop_failures[status],
            }, None
        clarification = str(
            result.get("reason")
            or "没有形成可以安全发送给外部 AI 的完整问题。"
        )
        action_context = (
            "EXTERNAL AI ACTION DID NOT SEND A PROMPT\n"
            "Do not claim ChatGPT was contacted. Ask one concise clarification "
            "or explain the privacy refusal.\n\n"
            + json.dumps(
                {
                    "success": False,
                    "needs_clarification": True,
                    "clarification": clarification,
                    "status": status or "NEEDS_CLARIFICATION",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return search_result, action_context

    if mode == "TASK_ACTION":
        import task_ai
        import tasks

        status_callback("正在理解任务… ✅")
        task_plan = task_ai.plan_task_action(message, recent_context)
        task_result = tasks.execute_task_plan(task_plan)
        print("[CASPER TASK RESULT]", json.dumps(task_result, ensure_ascii=False))
        action_context = (
            "CASPER TASK ACTION RESULT\n"
            "This is the authoritative result from Bekki's local Task system.\n"
            "Do not change, contradict, or invent its task data.\n\n"
            + json.dumps(task_result, ensure_ascii=False, indent=2)
            + "\n\nIf needs_clarification is true, ask exactly one concise "
            "clarifying question. Do not claim the task was saved unless "
            "success is true."
        )
        return search_result, action_context

    if mode == "DEVICE_ACTION":
        from . import device_actions

        status_callback("Casper 正在执行设备操作… 🧭")
        simple_app_target = ""
        steam_game_target = _steam_game_target(message)
        steam_library_list_requested = bool(
            melchior_plan.get("steam_library_list_selected")
        ) or _is_steam_library_list_request(message)
        if not any(
            (
                melchior_plan.get("content_workflow_selected"),
                melchior_plan.get("recycle_workflow_selected"),
                melchior_plan.get("content_resume_skill_id"),
                str(melchior_plan.get("skill_route") or "").lower()
                == "lookup",
            )
        ):
            if not steam_game_target and not steam_library_list_requested:
                simple_app_target = _simple_application_target(message)
        action_result = None
        if steam_library_list_requested:
            action_result = _list_installed_steam_games()
        elif steam_game_target:
            action_result = _launch_steam_game(steam_game_target)
            if action_result is None:
                action_result = {
                    "success": False,
                    "completed": False,
                    "needs_clarification": True,
                    "action": "steam_game_not_found",
                    "application": "Steam",
                    "game": steam_game_target,
                    "clarification": (
                        "没有在本机 Steam 库中找到与 " + steam_game_target
                        + " 明确匹配的已安装游戏。"
                    ),
                    "reason": (
                        "No installed Steam manifest could be selected with "
                        "high confidence."
                    ),
                }
        elif simple_app_target:
            if _is_genshin_target(simple_app_target):
                action_result = _launch_genshin_through_hoyoplay()
            else:
                action_result = _launch_start_menu_application(simple_app_target)
            if action_result is None:
                action_result = {
                    "success": False,
                    "completed": False,
                    "needs_clarification": True,
                    "action": "application_not_found",
                    "application": simple_app_target,
                    "clarification": (
                        "没有找到与 " + simple_app_target
                        + " 完全匹配且可启动的开始菜单应用。"
                    ),
                    "reason": (
                        "No exact launchable Start-menu identity or shortcut "
                        "was found; no window-selection model was used."
                    ),
                }
        else:
            action_result = device_actions.execute_user_request(
                message,
                recent_context,
                elevation_approved=bool(
                    melchior_plan.get("device_elevation_approved", False)
                ),
                device_approval=melchior_plan.get("device_action_approval"),
                content_workflow_selected=bool(
                    melchior_plan.get("content_workflow_selected", False)
                ),
                recycle_workflow_selected=bool(
                    melchior_plan.get("recycle_workflow_selected", False)
                ),
                file_workflow_selected=(
                    str(melchior_plan.get("device_scope") or "").upper()
                    == "FILE_ACTION"
                ),
                content_resume_skill_id=melchior_plan.get(
                    "content_resume_skill_id"
                ),
                skill_lookup_requested=(
                    str(melchior_plan.get("skill_route") or "").lower()
                    == "lookup"
                ),
            )
        if (
            simple_app_target
            and action_result.get("action") == "window_control_completed"
            and _application_key(simple_app_target)
            not in _application_key(action_result.get("window"))
        ):
            action_result = {
                "success": False,
                "completed": False,
                "needs_clarification": True,
                "action": "application_identity_mismatch",
                "application": simple_app_target,
                "clarification": (
                    "没有找到与 " + simple_app_target
                    + " 匹配的已安装应用；我没有切换到其他窗口。"
                ),
                "reason": "The selected window did not match the requested app.",
            }
        if (
            action_result.get("skill_state") in {"learned", "reused"}
            and action_result.get("action")
            in {"game_launch_dispatched", "game_opened"}
        ):
            print(
                "[CASPER GAME SKILL]",
                action_result.get("skill_state"),
                action_result.get("game"),
                "via",
                action_result.get("launch_route"),
            )
        elif action_result.get("skill_state") in {"learned", "reused"}:
            print(
                "[CASPER APP SKILL]",
                action_result.get("skill_state"),
                action_result.get("application"),
                "via",
                action_result.get("launch_route"),
            )
        print(
            "[CASPER DEVICE RESULT]",
            json.dumps(action_result, ensure_ascii=False),
        )
        action_context = (
            "CASPER DEVICE ACTION RESULT\n"
            "This is the authoritative result of the supervised local action.\n"
            "Do not claim an application opened unless success is true.\n"
            "For a requested game, success/completed must be true and action "
            "must be game_opened before saying the game opened or wishing the "
            "user fun. launcher_opened is incomplete even though the launcher "
            "window is visible.\n"
            "Use the AI post-launch verification status as the result. If action "
            "is launcher_opened, state that only the launcher opened. If action "
            "is uncertain, say the observed state is uncertain. Never claim the "
            "game itself started without game_opened.\n"
            "If needs_clarification is true, ask the supplied clarification "
            "question concisely. For system_control_completed or "
            "window_control_completed, state only the control actually "
            "reported as completed. For file actions, describe only the "
            "bounded folder/path operation reported by the result. Never say "
            "a path was opened or a folder was created unless success and "
            "completed are both true. For listed_folder, name the folder and "
            "show the returned items (or state that the returned list is "
            "empty). For searched_files, reproduce only paths present in "
            "matches; never propose or guess another location. If the reported "
            "folder differs from the requested one, "
            "state that mismatch; never turn a local device action into a web "
            "search or suggest a search pending_action.\n\n"
            + json.dumps(action_result, ensure_ascii=False, indent=2)
        )
        if (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "listed_steam_library"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_steam_library(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "listed_folder"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_listed_folder(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "searched_files"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_file_search(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "listed_recycle_bin"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_recycle_bin(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "opened_recycle_bin"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已打开回收站。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "restored_recycle_item"
        ):
            name = str(action_result.get("name") or "该项目")
            location = str(action_result.get("original_location") or "")
            suffix = "，原位置：" + location if location else ""
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已恢复 " + name + suffix + "。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "installed_fm_tactic"
        ):
            name = str(action_result.get("name") or "所选战术")
            destination = str(
                action_result.get("destination") or "FM26 tactics"
            )
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已安装 " + name + " 到 " + destination + "。",
            }
        elif (
            action_result.get("success")
            and action_result.get("action")
            in {
                "folder_skill_awaiting_user_verification",
                "tactic_recommendations_awaiting_folder_verification",
            }
            and action_result.get("requires_user_verification")
        ):
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "cards": action_result.get("cards", []),
                "pending_approval": {
                    "resume_after_user_confirmation": True,
                    "handoff_type": "skill_user_verification",
                    "event": "folder_skill_verification",
                    "original_request": action_result.get("original_request")
                    or message,
                    "approval_payload": {
                        "skill_candidate_id": action_result.get(
                            "skill_candidate_id"
                        ),
                        "target_app": action_result.get("target_app"),
                        "destination": action_result.get("destination_name"),
                        "verification_kind": "opened_destination_folder",
                        "recommendations_requested": (
                            action_result.get("action")
                            == "tactic_recommendations_awaiting_folder_verification"
                        ),
                        "recommendation_count": action_result.get(
                            "recommendation_count", 0
                        ),
                        "tactic_page_opened": action_result.get(
                            "tactic_page_opened", False
                        ),
                    },
                },
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "opened_fm_tactic_folder"
        ):
            destination = str(
                action_result.get("destination") or "FM26 战术文件夹"
            )
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已打开 " + destination + "。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action")
            == "opened_folder_and_recommended_tactics"
        ):
            count = int(action_result.get("recommendation_count") or 0)
            opened = bool(action_result.get("tactic_page_opened"))
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "cards": action_result.get("cards", []),
                "direct_reply": (
                    "已打开 FM26 战术文件夹，并推荐了 " + str(count)
                    + " 个战术。"
                    + ("最佳候选页面也已打开。" if opened else "")
                ),
            }
        elif (
            action_result.get("success")
            and action_result.get("action")
            == "learned_content_skill_candidate"
            and action_result.get("requires_continuation")
        ):
            target = str(action_result.get("target_app") or "目标应用")
            destination = str(
                action_result.get("destination_name") or "本地内容目录"
            )
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": {
                    "resume_after_user_confirmation": True,
                    "handoff_type": "content_learning_continue",
                    "event": "content_learning_complete",
                    "original_request": action_result.get("original_request")
                    or message,
                    "approval_payload": {
                        "skill_candidate_id": action_result.get(
                            "skill_candidate_id"
                        ),
                        "target_app": target,
                        "destination_name": destination,
                    },
                },
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action")
            == "content_installation_awaiting_user_verification"
            and action_result.get("requires_user_verification")
        ):
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": {
                    "resume_after_user_confirmation": True,
                    "handoff_type": "skill_user_verification",
                    "event": "skill_result_verification",
                    "original_request": action_result.get("original_request")
                    or message,
                    "approval_payload": {
                        "skill_candidate_id": action_result.get(
                            "skill_candidate_id"
                        ),
                        "target_app": action_result.get("target_app"),
                        "name": action_result.get("name"),
                        "destination": action_result.get("destination"),
                    },
                },
            }
        elif (
            action_result.get("success")
            and action_result.get("action")
            == "prepared_content_installation_manifest"
        ):
            manifest = action_result.get("manifest") or {}
            name = str(manifest.get("artifact_name") or "所选内容")
            target = str(manifest.get("target_app") or "目标游戏")
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": (
                    "已为 " + target + " 选出 " + name
                    + " 并整理安装方案；当前尚未下载或安装。"
                ),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "window_control_completed"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": _render_window_control(action_result),
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "game_opened"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已通过 HoYoPlay 打开原神。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "game_launch_dispatched"
            and action_result.get("application") == "HoYoPlay"
        ):
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已在 HoYoPlay 中点击开始游戏，原神正在启动。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "game_launch_dispatched"
        ):
            game = str(action_result.get("game") or steam_game_target or "游戏")
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已让 Steam 启动 " + game + "。",
            }
        elif (
            action_result.get("success")
            and action_result.get("completed")
            and action_result.get("action") == "application_opened"
        ):
            application = str(
                action_result.get("application") or simple_app_target or "应用"
            )
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": "已启动 " + application + "。",
            }
        if action_result.get("protected_event"):
            from .safety import reflex

            event = str(action_result.get("protected_event") or "access_block")
            handoff = reflex(event, "game-content research") or {}
            pending = handoff.get("pending_approval", {})
            pending.update(
                {
                    "resume_after_user_confirmation": True,
                    "original_request": message,
                    "handoff_type": (
                        "content_browser_handoff"
                        if action_result.get("resume_skill_id")
                        else "browser_handoff"
                    ),
                    "approval_payload": (
                        {
                            "skill_id": action_result.get(
                                "resume_skill_id"
                            )
                        }
                        if action_result.get("resume_skill_id")
                        else None
                    ),
                }
            )
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": pending,
            }
        elif (
            action_result.get("needs_clarification")
            and action_result.get("content_installation_retry_available")
            and action_result.get("resume_skill_id")
        ):
            clarification = str(
                action_result.get("clarification")
                or "这次没有完成内容获取。"
            )
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": {
                    "resume_after_user_confirmation": True,
                    "handoff_type": "content_learning_continue",
                    "event": "content_installation_retry",
                    "original_request": action_result.get("original_request")
                    or message,
                    "approval_payload": {
                        "skill_candidate_id": action_result.get(
                            "resume_skill_id"
                        ),
                        "target_app": action_result.get("target_app"),
                        "destination_name": action_result.get(
                            "destination_name"
                        ),
                        "clarification": clarification,
                    },
                },
            }
        elif action_result.get("needs_clarification"):
            clarification = str(
                action_result.get("clarification")
                or "需要补充一点信息才能继续。"
            )
            search_result = {
                "status": "LOCAL_ACTION_RESULT",
                "results": [],
                "direct_reply": clarification,
            }
        if action_result.get("requires_approval"):
            from .safety import reflex

            approval_type = str(
                action_result.get("approval_type") or "permission_escalation"
            )
            handoff = reflex(
                approval_type,
                action_result.get("application") or action_result.get("name", ""),
            ) or {}
            pending = handoff.get("pending_approval", {})
            pending.update(
                {
                    "resume_after_user_confirmation": True,
                    "original_request": message,
                    "handoff_type": "device_action_approval",
                    "approval_payload": {
                        "action": action_result.get("action"),
                        "candidate_id": action_result.get("candidate_id"),
                        "name": action_result.get("name"),
                        "original_location": action_result.get("original_location"),
                    },
                }
            )
            search_result = {
                "status": "HUMAN_HANDOFF",
                "results": [],
                "pending_approval": pending,
            }

        # Exact-resume checkpoint lifecycle metadata is structural.  A
        # terminal result consumes the stale checkpoint; a direct completed
        # result consumes it only when no replacement handoff is required.
        # Retry and verification handoffs replace the old checkpoint through
        # the normal atomic pending-action save in main.py.
        exact_resume_id = str(
            melchior_plan.get("content_resume_skill_id") or ""
        ).strip()
        if isinstance(search_result, dict) and exact_resume_id:
            if action_result.get("exact_resume_terminal") is True:
                search_result["clear_exact_resume_checkpoint"] = True
            elif (
                action_result.get("success") is True
                and action_result.get("completed") is True
                and search_result.get("status") != "HUMAN_HANDOFF"
            ):
                search_result["exact_resume_completed"] = True
        return search_result, action_context

    # Load the existing search/browser layer only for research modes.
    import tools

    if mode in {"NEWS_FEED", "FACT_LOOKUP", "CLAIM_CHECK", "SOCIAL_RESEARCH"}:
        try:
            tools.unload_model("gemma4:12b")
        except Exception as error:
            print("[CASPER MODEL UNLOAD SKIPPED] gemma4:12b", repr(error))

    if mode == "SOCIAL_RESEARCH":
        search_result = tools.social_research_controller(
            message,
            melchior_plan.get("social_platforms", []),
            status_callback=status_callback,
        )
        return search_result, action_context

    if mode in {"SHOPPING_RESEARCH", "RECOMMENDATION_RESEARCH"}:
        from . import browser as casper_browser

        allowed_domains = {
            "PRODUCT",
            "RESTAURANT",
            "LOCAL_SERVICE",
            "HEALTHCARE_PROVIDER",
            "TRAVEL_STAY",
            "TRAVEL_ACTIVITY",
            "SOFTWARE_TOOL",
            "MEDIA",
            "OTHER",
        }
        domain = str(
            melchior_plan.get("recommendation_domain") or "PRODUCT"
        ).upper().strip()
        if domain not in allowed_domains:
            domain = "PRODUCT"
        product_route = domain == "PRODUCT"
        try:
            if product_route:
                if mode == "RECOMMENDATION_RESEARCH":
                    search_result = casper_browser.product_recommendation_controller(
                        message,
                        recent_context,
                        status_callback=status_callback,
                    )
                else:
                    search_result = casper_browser.shopping_research_controller(
                        message,
                        recent_context,
                        status_callback=status_callback,
                    )
            else:
                from . import recommendation

                search_result = recommendation.research_controller(
                    message,
                    domain,
                    calibration,
                    recent_context,
                    status_callback=status_callback,
                )
        except Exception as error:
            print("[CASPER RECOMMENDATION BROWSER UNAVAILABLE]", repr(error))
            search_result = {
                "status": "BROWSER_UNAVAILABLE",
                "results": [],
                "cards": [],
            }

        if not isinstance(search_result, dict):
            search_result = {
                "status": "NO_RESULT",
                "results": [],
                "cards": [],
            }
        search_result["recommendation_domain"] = domain
        if product_route:
            evidence_route = (
                "independent_recommendation_sources"
                if mode == "RECOMMENDATION_RESEARCH"
                else (
                    "audited_exact_purchase_entries"
                    if search_result.get("lookup_mode") == "EXACT_PRODUCT"
                    else "verified_product_pages"
                )
            )
            search_result["evidence_route"] = evidence_route
            search_result["context"] = (
                "evidence_route: " + evidence_route + "\n"
                + str(search_result.get("context") or "")
            )

        return search_result, action_context

    status_callback("正在整理搜索问题… 🔍")

    if mode == "NEWS_FEED":
        queries = tools.build_news_queries(message, recent_context)
        from . import browser as casper_browser

        try:
            search_result = casper_browser.news_feed_controller(
                queries,
                user_request=message,
                status_callback=status_callback,
            )
        except Exception as error:
            print("[CASPER NEWS BROWSER UNAVAILABLE]", repr(error))
            search_result = {"status": "BROWSER_UNAVAILABLE", "results": []}

    elif mode == "FACT_LOOKUP":
        query = tools.build_search_query(message, recent_context)
        from . import browser as casper_browser

        try:
            search_result = casper_browser.fact_lookup_controller(
                query,
                user_request=message,
                status_callback=status_callback,
                risk=melchior_plan.get("risk", "low"),
            )
        except Exception as error:
            print("[CASPER BROWSER UNAVAILABLE]", repr(error))
            search_result = {"status": "BROWSER_UNAVAILABLE", "results": []}

    elif mode == "CLAIM_CHECK":
        query = tools.build_claim_query(
            melchior_plan.get("claim_to_verify") or message
        )
        search_result = tools.search_controller(
            query,
            status_callback=status_callback,
        )

    return search_result, action_context


def execute_pending_search(query, status_callback):
    import tools

    return tools.search_controller(query, status_callback)


def list_pending_tasks():
    import tasks

    task_data = tasks.load_tasks()
    pending = [
        task
        for task in task_data.get("tasks", [])
        if task.get("status") == "pending"
    ]
    pending.sort(key=lambda task: task.get("due_at", ""))
    return pending


def _task_ui_action(action, task_id, reason):
    import tasks

    return tasks.execute_task_plan(
        {
            "action": action,
            "task_id": task_id,
            "task_reference": None,
            "title": "",
            "due_at": None,
            "recurrence": "NONE",
            "clarification": None,
            "reason": reason,
        }
    )


def complete_task(task_id):
    return _task_ui_action(
        "COMPLETE",
        task_id,
        "User completed the task through the Task UI.",
    )


def delete_task(task_id, confirmed=False):
    if not confirmed:
        return {
            "success": False,
            "needs_confirmation": True,
            "message": "Task deletion requires confirmation.",
        }
    return _task_ui_action(
        "DELETE",
        task_id,
        "User confirmed task deletion through the Task UI.",
    )


def poll_due_notifications():
    import tasks

    return tasks.pop_due_notifications()


def clear_desktop_capture():
    import desktop

    return desktop.clear_capture()


def capture_screen():
    import desktop

    return desktop.capture_screen()


def capture_active_window():
    import desktop

    return desktop.capture_active_window()


def start_screen_snip():
    import desktop

    return desktop.start_screen_snip()


def capture_clipboard_image():
    import desktop

    return desktop.capture_clipboard_image()


def capture_qt_clipboard_image(qimage):
    import desktop

    return desktop.capture_qt_clipboard_image(qimage)
