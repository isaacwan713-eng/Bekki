"""Optional local Windows OCR support for screenshot text.

This module is deliberately a perception adapter, not another semantic model
or routing gate.  It returns fallible text evidence to the existing Gemma
vision call and fails open when Windows OCR is unavailable.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


_ALLOWED_STATUSES = {
    "COMPLETED",
    "DISABLED",
    "UNAVAILABLE",
    "TIMED_OUT",
    "FAILED",
}


def _bounded(value, maximum):
    return str(value or "").strip()[:maximum]


def _is_enabled():
    value = os.getenv("BEKKI_WINDOWS_OCR", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _is_windows():
    return os.name == "nt"


def _load_ocr_image(file_path):
    from PIL import Image, ImageOps

    with Image.open(file_path) as opened:
        image = ImageOps.exif_transpose(opened).copy()

    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("OCR image has invalid dimensions.")
    return image


def _resize_ocr_view(
    image,
    minimum_short_side=780,
    maximum_long_side=2400,
    maximum_scale=3.0,
):
    """Enlarge one geometric view without crossing WinRT's safe bound."""
    from PIL import Image, ImageFilter

    width, height = image.size
    scale = max(1.0, minimum_short_side / min(width, height))
    scale = min(scale, maximum_scale)
    if max(width, height) * scale > maximum_long_side:
        scale = maximum_long_side / max(width, height)

    if abs(scale - 1.0) >= 0.01:
        image = image.resize(
            (
                max(1, int(round(width * scale))),
                max(1, int(round(height * scale))),
            ),
            Image.Resampling.LANCZOS,
        )
        image = image.filter(
            ImageFilter.UnsharpMask(radius=1.0, percent=110, threshold=3)
        )
    return image


def _save_ocr_view(image, label="full"):
    descriptor, temporary_path = tempfile.mkstemp(
        prefix="bekki_windows_ocr_" + str(label).lower() + "_",
        suffix=".png",
    )
    os.close(descriptor)
    try:
        image.save(temporary_path, format="PNG")
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise
    return temporary_path


def _prepare_ocr_image(file_path):
    """Create the backward-compatible full screenshot OCR view."""
    image = _load_ocr_image(file_path)
    image = _resize_ocr_view(image)
    return _save_ocr_view(image, "full"), image.size


def _prepare_ocr_views(file_path):
    """Create full and overlapping detail views for one OCR request."""
    image = _load_ocr_image(file_path)
    width, height = image.size
    specifications = [("FULL", image, 780, 3.0)]

    if width >= 600 and width / height >= 2.0:
        midpoint = width // 2
        overlap = max(24, int(round(width * 0.14)))
        specifications.extend((
            (
                "LEFT_DETAIL",
                image.crop((0, 0, min(width, midpoint + overlap), height)),
                1100,
                4.5,
            ),
            (
                "RIGHT_DETAIL",
                image.crop((max(0, midpoint - overlap), 0, width, height)),
                1100,
                4.5,
            ),
        ))
    elif height >= 600 and height / width >= 2.0:
        midpoint = height // 2
        overlap = max(24, int(round(height * 0.14)))
        specifications.extend((
            (
                "TOP_DETAIL",
                image.crop((0, 0, width, min(height, midpoint + overlap))),
                1100,
                4.5,
            ),
            (
                "BOTTOM_DETAIL",
                image.crop((0, max(0, midpoint - overlap), width, height)),
                1100,
                4.5,
            ),
        ))

    prepared = []
    try:
        for label, view, minimum_short_side, maximum_scale in specifications:
            resized = _resize_ocr_view(
                view,
                minimum_short_side=minimum_short_side,
                maximum_scale=maximum_scale,
            )
            prepared.append({
                "view": label,
                "path": _save_ocr_view(resized, label),
                "size": resized.size,
            })
    except Exception:
        for item in prepared:
            try:
                os.unlink(item["path"])
            except OSError:
                pass
        raise
    return prepared


def _parse_powershell_output(output):
    candidates = [line.strip() for line in str(output or "").splitlines()]
    for candidate in reversed(candidates):
        candidate = candidate.lstrip("\ufeff")
        if not candidate.startswith("{"):
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalize_single_result(value):
    if not isinstance(value, dict):
        value = {}
    status = _bounded(value.get("status"), 40).upper()
    if status not in _ALLOWED_STATUSES:
        status = "FAILED"

    raw_lines = value.get("lines")
    lines = []
    if isinstance(raw_lines, list):
        for item in raw_lines[:80]:
            if isinstance(item, dict):
                text = _bounded(item.get("text"), 300)
                if text:
                    lines.append(text)
            else:
                text = _bounded(item, 300)
                if text:
                    lines.append(text)

    text = _bounded(value.get("text"), 6000)
    if not text and lines:
        text = "\n".join(lines)

    available = value.get("available_languages")
    if not isinstance(available, list):
        available = []

    return {
        "status": status,
        "view": _bounded(value.get("view"), 40).upper(),
        "language_tag": _bounded(value.get("language_tag"), 40),
        "language_match": _bounded(value.get("language_match"), 40),
        "preferred_language_available": bool(
            value.get("preferred_language_available")
        ),
        "text": text,
        "lines": lines,
        "available_languages": [
            _bounded(item, 40) for item in available[:24] if _bounded(item, 40)
        ],
        "reason": _bounded(value.get("reason"), 160),
        "error_stage": _bounded(value.get("error_stage"), 80),
        "error_type": _bounded(value.get("error_type"), 100),
        "error_hresult": _bounded(value.get("error_hresult"), 40),
    }


def _normalize_result(value):
    normalized = _normalize_single_result(value)
    raw_passes = value.get("passes") if isinstance(value, dict) else None
    passes = []
    if isinstance(raw_passes, list):
        for item in raw_passes[:5]:
            candidate = _normalize_single_result(item)
            if not candidate["view"]:
                candidate["view"] = "PASS_" + str(len(passes) + 1)
            passes.append(candidate)
    normalized["passes"] = passes
    return normalized


def extract_windows_ocr(file_path, timeout_seconds=15):
    """Read screenshot text locally with Windows.Media.Ocr when available."""
    if not _is_enabled():
        return _normalize_result({"status": "DISABLED", "reason": "disabled"})
    if not _is_windows():
        return _normalize_result(
            {"status": "UNAVAILABLE", "reason": "windows_only"}
        )
    if not file_path or not os.path.isfile(file_path):
        return _normalize_result(
            {"status": "FAILED", "reason": "image_missing"}
        )

    script_path = Path(__file__).resolve().with_name("WINDOWS_OCR.ps1")
    if not script_path.is_file():
        return _normalize_result(
            {"status": "UNAVAILABLE", "reason": "script_missing"}
        )

    powershell = shutil.which("powershell.exe")
    if not powershell:
        return _normalize_result(
            {"status": "UNAVAILABLE", "reason": "powershell_missing"}
        )

    temporary_views = []
    pass_results = []
    try:
        temporary_views = _prepare_ocr_views(file_path)
        preferred_language = os.getenv("BEKKI_OCR_LANGUAGE", "zh-CN").strip()
        deadline = time.monotonic() + max(3, int(timeout_seconds))
        for view in temporary_views:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                pass_results.append(_normalize_single_result({
                    "status": "TIMED_OUT",
                    "view": view["view"],
                    "reason": "ocr_total_timeout",
                }))
                break
            command = [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ImagePath",
                view["path"],
                "-PreferredLanguageTag",
                preferred_language or "zh-CN",
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(0.5, remaining),
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                result = _parse_powershell_output(completed.stdout)
                if not result:
                    result = {
                        "status": "FAILED",
                        "reason": "invalid_ocr_output",
                        "error_stage": "parse_output",
                        "error_type": "PowerShellExit" + str(
                            completed.returncode
                        ),
                    }
            except subprocess.TimeoutExpired:
                result = {
                    "status": "TIMED_OUT",
                    "reason": "ocr_total_timeout",
                }
            result["view"] = view["view"]
            pass_results.append(_normalize_single_result(result))
            if result.get("status") == "TIMED_OUT":
                break
    except Exception as error:
        return _normalize_result(
            {
                "status": "FAILED",
                "reason": "ocr_adapter_failed",
                "error_stage": "python_adapter",
                "error_type": type(error).__name__,
            }
        )
    finally:
        for view in temporary_views:
            try:
                os.unlink(view["path"])
            except OSError:
                pass

    completed_passes = [
        item for item in pass_results
        if item["status"] == "COMPLETED" and item["text"]
    ]
    if completed_passes:
        primary = next(
            (item for item in completed_passes if item["view"] == "FULL"),
            completed_passes[0],
        )
        aggregate = dict(primary)
        aggregate["status"] = "COMPLETED"
        aggregate["reason"] = ""
        aggregate["passes"] = pass_results
        return _normalize_result(aggregate)
    if pass_results:
        aggregate = dict(pass_results[0])
        aggregate["passes"] = pass_results
        return _normalize_result(aggregate)
    return _normalize_result({
        "status": "FAILED",
        "reason": "no_ocr_pass_completed",
        "error_stage": "python_adapter",
    })


def format_ocr_context(result):
    """Format bounded OCR evidence for the existing vision-model call."""
    normalized = _normalize_result(result)
    if normalized["status"] != "COMPLETED" or not normalized["text"]:
        return "No usable local OCR transcription was available."
    observations = []
    for item in normalized.get("passes", []):
        if item["status"] == "COMPLETED" and item["text"]:
            observations.append({
                "view": item["view"],
                "transcription": item["text"],
            })
    if not observations:
        observations.append({
            "view": normalized.get("view") or "FULL",
            "transcription": normalized["text"],
        })
    packet = {
        "reader": "Windows.Media.Ocr",
        "recognizer_language": normalized["language_tag"],
        "preferred_language_available": normalized[
            "preferred_language_available"
        ],
        "transcription": normalized["text"],
        "observations": observations,
    }
    return json.dumps(packet, ensure_ascii=False)
