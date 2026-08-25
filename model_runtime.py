"""Bounded Ollama runtime for Bekki's local models.

This module is the only place where Bekki should generate with Ollama.  It
serializes requests across both threads and processes, keeps model budgets
inside the 16 GB stability envelope, and performs one clean retry after a
recoverable Ollama/CUDA failure.
"""

from contextlib import contextmanager
import os
import re
import tempfile
import threading
import time

import requests


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
).strip()
OLLAMA_PS_URL = OLLAMA_URL.rsplit("/", 1)[0] + "/ps"
DEFAULT_MODEL = "gemma3:12b"
KNOWN_MODELS = {
    "gemma3:12b",
    "gemma3:4b",
    "llama3.2:latest",
}

_THREAD_LOCK = threading.RLock()
_WINDOWS_MUTEX_NAME = "Local\\BekkiOllamaRuntimeV1"
_LOCK_FILE = os.path.join(tempfile.gettempdir(), "bekki_ollama_runtime_v1.lock")


class OllamaRuntimeError(RuntimeError):
    """A bounded model request failed after Bekki's recovery attempt."""


def _bounded_env_number(name, default, minimum, maximum):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    return max(float(minimum), min(value, float(maximum)))


def _normalize_model(model_name):
    requested = str(model_name or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    size_match = re.search(r"(?:^|[:_-])(\d+(?:\.\d+)?)b(?:$|[-_])", requested, re.I)
    if size_match and float(size_match.group(1)) > 12:
        print("[MODEL REMAPPED]", requested, "->", DEFAULT_MODEL)
        return DEFAULT_MODEL
    return requested


def _bounded_options(model_name, num_ctx, num_predict, retry=False):
    compact_model = str(model_name).casefold().startswith(
        ("gemma3:4b", "llama3.2:")
    )
    max_ctx = 4096 if compact_model else 8192
    max_predict = 2048 if compact_model else 4096
    try:
        context_size = int(num_ctx)
    except (TypeError, ValueError):
        context_size = max_ctx
    try:
        prediction_size = int(num_predict)
    except (TypeError, ValueError):
        prediction_size = 2048
    context_size = max(512, min(context_size, max_ctx))
    prediction_size = max(32, min(prediction_size, max_predict))
    if retry:
        context_size = min(context_size, 4096)
        prediction_size = min(prediction_size, 1024)
    return context_size, prediction_size


def _truncate_utf8_middle(value, maximum_bytes):
    """Keep instruction prefix and current-request suffix within a byte cap."""
    text = str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return text
    marker = "\n\n[... BEKKI INPUT COMPACTED FOR MODEL SAFETY ...]\n\n"
    marker_bytes = marker.encode("utf-8")
    available = max(512, maximum_bytes - len(marker_bytes))
    head_budget = int(available * 0.58)
    tail_budget = available - head_budget
    head = encoded[:head_budget].decode("utf-8", errors="ignore")
    tail = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    return head + marker + tail


def _prompt_for_budget(prompt, context_size, prediction_size, stage=None):
    del prediction_size
    bytes_per_context_token = _bounded_env_number(
        "BEKKI_PROMPT_BYTES_PER_TOKEN",
        3.4,
        2.5,
        4.0,
    )
    maximum_bytes = max(12000, int(context_size * bytes_per_context_token))
    original_bytes = len(str(prompt or "").encode("utf-8"))
    compacted = _truncate_utf8_middle(prompt, maximum_bytes)
    compacted_bytes = len(compacted.encode("utf-8"))
    if compacted_bytes < original_bytes:
        print(
            "[PROMPT BYTE BUDGET]",
            "stage=" + str(stage or "unspecified"),
            "original=" + str(original_bytes),
            "sent=" + str(compacted_bytes),
            "limit=" + str(maximum_bytes),
        )
    return compacted


@contextmanager
def _process_lock(timeout_seconds):
    """Serialize Ollama work between the UI and scheduler processes."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        create_mutex.restype = wintypes.HANDLE
        wait_for_single_object = kernel32.WaitForSingleObject
        wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        wait_for_single_object.restype = wintypes.DWORD
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = (wintypes.HANDLE,)
        release_mutex.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        handle = create_mutex(None, False, _WINDOWS_MUTEX_NAME)
        if not handle:
            raise OSError(ctypes.get_last_error(), "Could not create model mutex")
        acquired = False
        try:
            result = wait_for_single_object(handle, int(timeout_seconds * 1000))
            acquired = result in (0x00000000, 0x00000080)
            if not acquired:
                raise TimeoutError("Timed out waiting for another Bekki model task")
            yield
        finally:
            if acquired:
                release_mutex(handle)
            close_handle(handle)
        return

    lock_file = open(_LOCK_FILE, "a+b")
    try:
        try:
            import fcntl
        except ImportError:
            yield
            return
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for another Bekki model task")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


@contextmanager
def _serialized_runtime():
    lock_timeout = _bounded_env_number("BEKKI_MODEL_LOCK_TIMEOUT", 240, 30, 600)
    with _THREAD_LOCK:
        with _process_lock(lock_timeout):
            yield


def loaded_models():
    try:
        response = requests.get(OLLAMA_PS_URL, timeout=(3, 5))
        response.raise_for_status()
        models = response.json().get("models", [])
    except (requests.RequestException, TypeError, ValueError):
        return []
    return [
        str(item.get("name") or item.get("model") or "").strip()
        for item in models
        if isinstance(item, dict)
        and str(item.get("name") or item.get("model") or "").strip()
    ]


def _raw_unload(model_name):
    response = requests.post(
        OLLAMA_URL,
        json={"model": model_name, "keep_alive": 0},
        timeout=(5, 30),
    )
    response.raise_for_status()
    print("[MODEL UNLOADED]", model_name)


def wait_for_model_unloaded(model_name, timeout_seconds=10):
    deadline = time.monotonic() + max(1, min(float(timeout_seconds), 30))
    requested = str(model_name or "").casefold()
    while time.monotonic() < deadline:
        if requested not in {name.casefold() for name in loaded_models()}:
            return True
        time.sleep(0.25)
    return False


def _unload_other_models(selected_model):
    selected = str(selected_model).casefold()
    for loaded_model in loaded_models():
        if loaded_model.casefold() == selected:
            continue
        try:
            _raw_unload(loaded_model)
            wait_for_model_unloaded(loaded_model, timeout_seconds=10)
        except requests.RequestException as exc:
            print("[MODEL CLEANUP WARNING]", loaded_model, repr(exc))


def _recoverable_error(exc):
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None and int(status_code) >= 500:
        return True
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "cuda",
            "llama-server",
            "shared object initialization failed",
            "0xc0000409",
            "out of memory",
            "connection aborted",
            "connection reset",
        )
    )


def _request(payload):
    request_timeout = _bounded_env_number("BEKKI_MODEL_TIMEOUT", 180, 30, 300)
    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=(10, request_timeout),
    )
    if not response.ok:
        error_body = str(response.text or "").strip().replace("\n", " ")[:1200]
        print(
            "[OLLAMA HTTP ERROR]",
            "status=" + str(response.status_code),
            "model=" + str(payload["model"]),
            "num_ctx=" + str(payload["options"]["num_ctx"]),
            "num_predict=" + str(payload["options"]["num_predict"]),
            "body=" + repr(error_body),
        )
    response.raise_for_status()
    data = response.json()
    print("DONE REASON:", data.get("done_reason"))
    print("THINKING:", repr(data.get("thinking", "")))
    print("RESPONSE:", repr(data.get("response", "")))
    return str(data.get("response", "")).strip()


def generate(
    prompt,
    num_ctx=8192,
    num_predict=2048,
    think="low",
    model_name=None,
    response_format=None,
    images=None,
    keep_alive=None,
    stage=None,
):
    selected_model = _normalize_model(model_name)
    if (
        selected_model.casefold().startswith(("gemma3:", "llama3.2:"))
        and think not in {False, None}
    ):
        think = False

    try:
        with _serialized_runtime():
            _unload_other_models(selected_model)
            last_error = None
            for attempt in range(2):
                context_size, prediction_size = _bounded_options(
                    selected_model,
                    num_ctx,
                    num_predict,
                    retry=bool(attempt),
                )
                payload = {
                    "model": selected_model,
                    "prompt": _prompt_for_budget(
                        prompt,
                        context_size,
                        prediction_size,
                        stage=stage,
                    ),
                    "stream": False,
                    "think": think,
                    "options": {
                        "temperature": 0,
                        "num_ctx": context_size,
                        "num_predict": prediction_size,
                    },
                }
                if response_format is not None:
                    payload["format"] = response_format
                if images:
                    payload["images"] = [
                        str(image)
                        for image in images
                        if isinstance(image, str) and image.strip()
                    ]
                if keep_alive is not None:
                    payload["keep_alive"] = keep_alive
                try:
                    return _request(payload)
                except (requests.RequestException, TypeError, ValueError) as exc:
                    last_error = exc
                    if attempt or not _recoverable_error(exc):
                        break
                    print(
                        "[MODEL RECOVERY]",
                        "stage=" + str(stage or "unspecified"),
                        "model=" + selected_model,
                        "error=" + repr(exc),
                    )
                    try:
                        _raw_unload(selected_model)
                        wait_for_model_unloaded(selected_model, timeout_seconds=15)
                    except requests.RequestException as cleanup_error:
                        print("[MODEL RECOVERY CLEANUP WARNING]", repr(cleanup_error))
                    time.sleep(0.5)
            raise OllamaRuntimeError(
                "Bekki 的本地模型暂时不可用。已自动清理显存并重试；"
                "请确认 Ollama 正在运行后再试。"
            ) from last_error
    except TimeoutError as exc:
        raise OllamaRuntimeError(
            "Bekki 的模型任务正在排队且等待超时，请稍后再试。"
        ) from exc


def unload_model(model_name=DEFAULT_MODEL):
    selected_model = _normalize_model(model_name)
    with _serialized_runtime():
        _raw_unload(selected_model)
        return wait_for_model_unloaded(selected_model, timeout_seconds=10)


def runtime_snapshot():
    return {
        "loaded_models": loaded_models(),
        "max_12b_context": 8192,
        "retry_limit": 1,
        "cross_process_lock": True,
    }
