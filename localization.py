"""Bekki system-language settings and translations."""

import json
import os


SETTINGS_FILE = os.path.join("data", "app_settings.json")
SUPPORTED_LANGUAGES = {
    "zh-CN": "简体中文",
    "en": "English",
    "es": "Español",
    "ja": "日本語",
}
LANGUAGE_BADGES = {"zh-CN": "中", "en": "EN", "es": "ES", "ja": "日"}
DEFAULT_LANGUAGE = "zh-CN"

TEXT = {
    "zh-CN": {
        "language": "系统语言", "history_toggle": "显示 / 隐藏聊天记录",
        "chats": "聊天", "new_chat": "＋  新对话", "new_chat_title": "新对话",
        "clear_chat": "清除当前聊天", "reset_context": "重置当前 Context",
        "delete_chat": "删除这个对话", "input_placeholder": "和 Bekki 聊点什么吧…",
        "attach": "添加文件或图片", "desktop": "桌面视觉与截图", "send": "发送",
        "remove_attachment": "移除当前附件", "added": "已添加到当前对话",
        "document_ready": "已加载 · 可以直接询问文件内容",
        "image_ready": "已加载 · 可以直接询问画面内容",
        "screen": "读取主显示器", "screen_desc": "分析当前屏幕上的完整画面",
        "window": "读取活动窗口", "window_desc": "只分析你正在使用的窗口",
        "snip": "框选截图", "snip_desc": "自由选择一个区域交给 Bekki",
        "undo": "撤销", "redo": "重做", "cut": "剪切", "copy": "复制",
        "paste": "粘贴", "delete": "删除", "select_all": "全选",
        "source_open": "在浏览器中打开来源", "more_sources": "查看其余来源",
        "status_language": "界面语言已切换为简体中文 ✨",
        "thinking": "正在思考… ✨", "routing": "正在判断问题… ✨",
        "emotion": "正在感受你的语气… 🩵", "query": "正在整理搜索问题… 🔍",
        "vision": "正在切换视觉模型… 👀", "reply": "正在生成回复… 💭",
        "reading_file": "正在读取文件… 📎", "desktop_read": "准备读取桌面… 👀",
        "window_read": "准备读取当前窗口… 👀", "select_region": "请框选需要读取的区域… ✂",
        "failed": "呜，刚才处理失败了：{error}",
        "choose_file": "选择文件",
        "identity_creator": "Bekki 是由 YW49 创建并持续维护的本地个人 AI 助手哦 🩵",
        "identity_company": "不是哦。Bekki 是 YW49 创建和维护的本地个人 AI 助手，不是 OpenAI、ChatGPT 或其他 AI 公司的官方产品。普通聊天目前通过本地 Ollama 调用 gpt-oss:20b 来生成回复 🩵",
        "identity_model": "我现在通过本地 Ollama 运行：普通聊天使用 gpt-oss:20b，图片理解使用 gemma3:12b。它们是 Bekki 的底层模型，Bekki 本身由 YW49 创建和维护 ✨",
        "task_understanding": "正在理解任务和时间… ⏰",
        "reminder_title": "Bekki 提醒你",
        "tasks": "任务",
        "no_pending_tasks": "暂时没有待办任务 ✨",
        "untitled_task": "未命名任务",
        "complete_task": "标记为完成",
        "delete_task": "删除任务",
        "task_time_unknown": "时间未确定",
        "recurrence_daily": "每天",
        "recurrence_weekly": "每周",
        "recurrence_monthly": "每月",
        "task_completed": "任务已完成 ✨",
        "task_deleted": "任务已删除",
        "confirm_task_delete_title": "删除任务？",
        "confirm_task_delete_text": "确定删除任务“{title}”吗？",
        "task_action_failed": "任务操作失败：{error}",
    },
    "en": {
        "language": "System language", "history_toggle": "Show / hide chat history",
        "chats": "Chats", "new_chat": "＋  New chat", "new_chat_title": "New chat",
        "clear_chat": "Clear current chat", "reset_context": "Reset current context",
        "delete_chat": "Delete this chat", "input_placeholder": "Message Bekki…",
        "attach": "Add a file or image", "desktop": "Desktop vision and screenshots", "send": "Send",
        "remove_attachment": "Remove current attachment", "added": "Added to this chat",
        "document_ready": "Ready · Ask anything about this document",
        "image_ready": "Ready · Ask anything about this image",
        "screen": "Read main display", "screen_desc": "Analyze everything visible on the screen",
        "window": "Read active window", "window_desc": "Analyze only the window you are using",
        "snip": "Capture a region", "snip_desc": "Select an area for Bekki to inspect",
        "undo": "Undo", "redo": "Redo", "cut": "Cut", "copy": "Copy",
        "paste": "Paste", "delete": "Delete", "select_all": "Select all",
        "source_open": "Open source in browser", "more_sources": "View remaining sources",
        "status_language": "Interface language changed to English ✨",
        "thinking": "Thinking… ✨", "routing": "Understanding your request… ✨",
        "emotion": "Reading your tone… 🩵", "query": "Preparing the search… 🔍",
        "vision": "Switching to vision… 👀", "reply": "Writing a response… 💭",
        "reading_file": "Reading the file… 📎", "desktop_read": "Preparing to read the desktop… 👀",
        "window_read": "Preparing to read the active window… 👀", "select_region": "Select the area to read… ✂",
        "failed": "Something went wrong: {error}", "choose_file": "Choose a file",
        "identity_creator": "Bekki is a local personal AI assistant created and maintained by YW49 🩵",
        "identity_company": "No. Bekki is a local personal AI assistant created and maintained by YW49, not an official product of OpenAI, ChatGPT, or another AI company. Normal chat currently runs gpt-oss:20b locally through Ollama 🩵",
        "identity_model": "I run locally through Ollama: normal chat uses gpt-oss:20b and image understanding uses gemma3:12b. They are Bekki's underlying models; Bekki is created and maintained by YW49 ✨",
        "task_understanding": "Understanding the task and time… ⏰",
        "reminder_title": "Bekki reminder",
        "tasks": "Tasks",
        "no_pending_tasks": "No pending tasks ✨",
        "untitled_task": "Untitled task",
        "complete_task": "Mark as complete",
        "delete_task": "Delete task",
        "task_time_unknown": "Time not set",
        "recurrence_daily": "Daily",
        "recurrence_weekly": "Weekly",
        "recurrence_monthly": "Monthly",
        "task_completed": "Task completed ✨",
        "task_deleted": "Task deleted",
        "confirm_task_delete_title": "Delete task?",
        "confirm_task_delete_text": "Delete “{title}”?",
        "task_action_failed": "Task action failed: {error}",
    },
    "es": {
        "language": "Idioma del sistema", "history_toggle": "Mostrar u ocultar el historial",
        "chats": "Chats", "new_chat": "＋  Nuevo chat", "new_chat_title": "Nuevo chat",
        "clear_chat": "Borrar chat actual", "reset_context": "Restablecer contexto",
        "delete_chat": "Eliminar este chat", "input_placeholder": "Escribe a Bekki…",
        "attach": "Añadir archivo o imagen", "desktop": "Visión del escritorio y capturas", "send": "Enviar",
        "remove_attachment": "Quitar archivo adjunto", "added": "Añadido a este chat",
        "document_ready": "Listo · Pregunta sobre este documento",
        "image_ready": "Listo · Pregunta sobre esta imagen",
        "screen": "Leer pantalla principal", "screen_desc": "Analizar todo lo visible en pantalla",
        "window": "Leer ventana activa", "window_desc": "Analizar solo la ventana actual",
        "snip": "Capturar una región", "snip_desc": "Selecciona un área para que Bekki la examine",
        "undo": "Deshacer", "redo": "Rehacer", "cut": "Cortar", "copy": "Copiar",
        "paste": "Pegar", "delete": "Eliminar", "select_all": "Seleccionar todo",
        "source_open": "Abrir fuente en el navegador", "more_sources": "Ver fuentes restantes",
        "status_language": "Idioma de la interfaz cambiado a Español ✨",
        "thinking": "Pensando… ✨", "routing": "Entendiendo tu solicitud… ✨",
        "emotion": "Interpretando tu tono… 🩵", "query": "Preparando la búsqueda… 🔍",
        "vision": "Activando la visión… 👀", "reply": "Redactando la respuesta… 💭",
        "reading_file": "Leyendo el archivo… 📎", "desktop_read": "Preparando la lectura del escritorio… 👀",
        "window_read": "Preparando la ventana activa… 👀", "select_region": "Selecciona el área… ✂",
        "failed": "Algo salió mal: {error}", "choose_file": "Elegir un archivo",
        "identity_creator": "Bekki es una asistente personal local de IA creada y mantenida por YW49 🩵",
        "identity_company": "No. Bekki es una asistente personal local creada y mantenida por YW49; no es un producto oficial de OpenAI, ChatGPT ni de otra empresa de IA. El chat normal usa gpt-oss:20b localmente mediante Ollama 🩵",
        "identity_model": "Funciono localmente mediante Ollama: el chat normal usa gpt-oss:20b y la visión usa gemma3:12b. Son los modelos subyacentes de Bekki; YW49 crea y mantiene Bekki ✨",
        "task_understanding": "Interpretando la tarea y la hora… ⏰",
        "reminder_title": "Recordatorio de Bekki",
        "tasks": "Tareas",
        "no_pending_tasks": "No hay tareas pendientes ✨",
        "untitled_task": "Tarea sin título",
        "complete_task": "Marcar como completada",
        "delete_task": "Eliminar tarea",
        "task_time_unknown": "Hora no definida",
        "recurrence_daily": "Diario",
        "recurrence_weekly": "Semanal",
        "recurrence_monthly": "Mensual",
        "task_completed": "Tarea completada ✨",
        "task_deleted": "Tarea eliminada",
        "confirm_task_delete_title": "¿Eliminar tarea?",
        "confirm_task_delete_text": "¿Eliminar “{title}”?",
        "task_action_failed": "Error al procesar la tarea: {error}",

    },
    "ja": {
        "language": "システム言語", "history_toggle": "チャット履歴を表示 / 非表示",
        "chats": "チャット", "new_chat": "＋  新しいチャット", "new_chat_title": "新しいチャット",
        "clear_chat": "現在のチャットを消去", "reset_context": "コンテキストをリセット",
        "delete_chat": "このチャットを削除", "input_placeholder": "Bekkiにメッセージ…",
        "attach": "ファイルまたは画像を追加", "desktop": "デスクトップ視覚とスクリーンショット", "send": "送信",
        "remove_attachment": "添付を削除", "added": "このチャットに追加済み",
        "document_ready": "準備完了 · この文書について質問できます",
        "image_ready": "準備完了 · この画像について質問できます",
        "screen": "メイン画面を読む", "screen_desc": "画面全体の表示内容を解析します",
        "window": "アクティブ画面を読む", "window_desc": "使用中のウィンドウだけを解析します",
        "snip": "範囲をキャプチャ", "snip_desc": "Bekkiに見せる範囲を選択します",
        "undo": "元に戻す", "redo": "やり直す", "cut": "切り取り", "copy": "コピー",
        "paste": "貼り付け", "delete": "削除", "select_all": "すべて選択",
        "source_open": "ブラウザで情報源を開く", "more_sources": "残りの情報源を見る",
        "status_language": "表示言語を日本語に変更しました ✨",
        "thinking": "考えています… ✨", "routing": "リクエストを確認しています… ✨",
        "emotion": "あなたのトーンを感じ取っています… 🩵", "query": "検索を準備しています… 🔍",
        "vision": "画像認識に切り替えています… 👀", "reply": "返信を作成しています… 💭",
        "reading_file": "ファイルを読んでいます… 📎", "desktop_read": "デスクトップを読み取る準備中… 👀",
        "window_read": "アクティブウィンドウを準備中… 👀", "select_region": "読み取る範囲を選択してください… ✂",
        "failed": "処理中に問題が発生しました：{error}", "choose_file": "ファイルを選択",
        "identity_creator": "BekkiはYW49が開発・保守しているローカル個人AIアシスタントです 🩵",
        "identity_company": "いいえ。BekkiはYW49が開発・保守するローカル個人AIアシスタントであり、OpenAI、ChatGPT、その他AI企業の公式製品ではありません。通常のチャットはOllama経由でローカルのgpt-oss:20bを使用します 🩵",
        "identity_model": "Ollamaを通じてローカルで動作しています。通常のチャットはgpt-oss:20b、画像理解はgemma3:12bを使用します。これらは基盤モデルで、BekkiはYW49が開発・保守しています ✨",
        "task_understanding": "タスクと時刻を確認しています… ⏰",
        "reminder_title": "Bekkiのリマインダー",
        "tasks": "タスク",
        "no_pending_tasks": "保留中のタスクはありません ✨",
        "untitled_task": "無題のタスク",
        "complete_task": "完了にする",
        "delete_task": "タスクを削除",
        "task_time_unknown": "時刻未設定",
        "recurrence_daily": "毎日",
        "recurrence_weekly": "毎週",
        "recurrence_monthly": "毎月",
        "task_completed": "タスクを完了しました ✨",
        "task_deleted": "タスクを削除しました",
        "confirm_task_delete_title": "タスクを削除しますか？",  
        "confirm_task_delete_text": "「{title}」を削除しますか？",
        "task_action_failed": "タスク操作に失敗しました：{error}",

    },
}


def _load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def get_language():
    value = _load_settings().get("language", DEFAULT_LANGUAGE)
    return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def set_language(language):
    if language not in SUPPORTED_LANGUAGES:
        return False
    settings = _load_settings()
    settings["language"] = language
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    temporary = SETTINGS_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
    os.replace(temporary, SETTINGS_FILE)
    return True


def t(key, **values):
    language = get_language()
    template = TEXT.get(language, TEXT[DEFAULT_LANGUAGE]).get(
        key, TEXT[DEFAULT_LANGUAGE].get(key, key)
    )
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return template


def badge():
    return LANGUAGE_BADGES[get_language()]


def ai_language_context():
    code = get_language()
    name = SUPPORTED_LANGUAGES[code]
    return (
        "Bekki system language: " + name + " (" + code + ").\n"
        "Use this as the default language for the final reply and user-facing "
        "pending action text. If the Current User Message explicitly requests "
        "another language, follow that request for this reply. Do not translate "
        "proper names, code, URLs, or quoted text unnecessarily."
    )
