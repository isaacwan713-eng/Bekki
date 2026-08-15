import base64
import json
import os

import requests
from dotenv import load_dotenv
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
)

VISION_MODEL = os.getenv(
    "VISION_MODEL",
    "gemma3:12b",
)

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

MAX_IMAGE_SIZE = 20 * 1024 * 1024


_current_image = {
    "file_name": None,
    "file_path": None,
    "size": 0,
}


def _detect_image_type(file_path):
    with open(file_path, "rb") as file:
        header = file.read(12)

    if header.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        return ".png"

    if header.startswith(b"\xff\xd8\xff"):
        return ".jpeg"

    if (
        len(header) >= 12
        and header[:4] == b"RIFF"
        and header[8:12] == b"WEBP"
    ):
        return ".webp"

    return None


def validate_image(file_path):
    if not file_path:
        return {
            "success": False,
            "error": "No image path provided.",
        }

    if not os.path.isfile(file_path):
        return {
            "success": False,
            "error": "Image file does not exist.",
        }

    extension = os.path.splitext(
        file_path
    )[1].lower()

    if extension not in (
        SUPPORTED_IMAGE_EXTENSIONS
    ):
        return {
            "success": False,
            "error": (
                "Unsupported image type: "
                + extension
            ),
        }

    file_size = os.path.getsize(
        file_path
    )

    if file_size <= 0:
        return {
            "success": False,
            "error": "Image file is empty.",
        }

    if file_size > MAX_IMAGE_SIZE:
        return {
            "success": False,
            "error": (
                "Image is too large. "
                "Maximum size is 20 MB."
            ),
        }

    detected_type = _detect_image_type(
        file_path
    )

    if detected_type is None:
        return {
            "success": False,
            "error": (
                "The selected file is not "
                "a readable PNG, JPEG, or WEBP image."
            ),
        }

    if (
        extension == ".png"
        and detected_type != ".png"
    ):
        return {
            "success": False,
            "error": (
                "Image extension does not "
                "match its file content."
            ),
        }

    if (
        extension in {".jpg", ".jpeg"}
        and detected_type != ".jpeg"
    ):
        return {
            "success": False,
            "error": (
                "Image extension does not "
                "match its file content."
            ),
        }

    if (
        extension == ".webp"
        and detected_type != ".webp"
    ):
        return {
            "success": False,
            "error": (
                "Image extension does not "
                "match its file content."
            ),
        }

    return {
        "success": True,
        "file_name": os.path.basename(
            file_path
        ),
        "file_path": file_path,
        "size": file_size,
        "error": None,
    }


def load_image(file_path):
    global _current_image

    result = validate_image(
        file_path
    )

    if not result.get("success"):
        return result

    # Only replace the active image after
    # validation has completely succeeded.
    _current_image = {
        "file_name": result["file_name"],
        "file_path": result["file_path"],
        "size": result["size"],
    }

    return result


def has_image():
    return bool(
        _current_image.get("file_path")
    )


def get_current_image():
    return _current_image


def clear_image():
    global _current_image

    _current_image = {
        "file_name": None,
        "file_path": None,
        "size": 0,
    }

def _get_model_image_bytes(file_path):
    extension = os.path.splitext(
        file_path
    )[1].lower()

    if extension != ".webp":
        with open(
            file_path,
            "rb",
        ) as file:
            return file.read()

    image = QImage(file_path)

    if image.isNull():
        raise ValueError(
            "WEBP image could not be decoded."
        )

    buffer = QBuffer()
    buffer.open(
        QIODevice.WriteOnly
    )

    if not image.save(buffer, "PNG"):
        raise ValueError(
            "WEBP image could not be converted to PNG."
        )

    return bytes(buffer.data())

def analyze_image(
    user_question,
    status_callback=None,
):
    if not has_image():
        return ""

    if status_callback:
        status_callback(
            "正在理解图片… 👀"
        )

    image = get_current_image()

    image_bytes = _get_model_image_bytes(
        image["file_path"]
    )

    image_base64 = (base64.b64encode(
        image_bytes
    ).decode("utf-8"))
    

    prompt = """
You are Bekki's vision evidence extractor.

Analyze the attached image for the user's
current question.

Do not speak to the user directly.
Do not use markdown.
Do not invent unreadable details.

Return valid JSON with exactly these fields:

{
  "summary": "brief visual description",
  "visible_text": ["important visible text"],
  "details": ["details relevant to the question"],
  "uncertainty": ["anything unclear"]
}

Current user question:
""" + user_question

    payload = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [image_base64],
        "format": "json",
        "stream": False,
        "keep_alive": "0s",
        "options": {
            "temperature": 0,
            "num_ctx": 2048,
            "num_predict": 256,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=180,
    )

    if not response.ok:
        print(
            "[VISION API ERROR]",
            response.status_code,
            response.text,
        )

        raise RuntimeError(
            "Vision model rejected this image:"
            + response.text
        )

    raw_output = (
        response.json()
        .get("response", "")
        .strip()
    )

    try:
        evidence = json.loads(
            raw_output
        )

    except json.JSONDecodeError:
        return (
            "Current Image: "
            + image["file_name"]
            + "\n\nRaw Vision Evidence:\n"
            + raw_output
        )

    return (
        "Current Image: "
        + image["file_name"]
        + "\n\nStructured Vision Evidence:\n"
        + json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        )
    )