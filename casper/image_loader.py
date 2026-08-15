# Bekki AI
# Created by YW49
# Copyright (c) 2026 YW49. All rights reserved.

"""Bounded asynchronous image loading for result cards."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests
from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    Signal,
)


MAX_IMAGE_BYTES = (
    5 * 1024 * 1024
)

MAX_REDIRECTS = 3
REQUEST_TIMEOUT = 12
MAX_MEMORY_CACHE_ITEMS = 32

_IMAGE_CACHE = {}
_IMAGE_CACHE_ORDER = []


def _safe_https_url(value):
    if not isinstance(
        value,
        str,
    ):
        return None

    value = value.strip()

    if not value:
        return None

    try:
        parsed = urlparse(
            value
        )

    except ValueError:
        return None

    if parsed.scheme.lower() != "https":
        return None

    if not parsed.hostname:
        return None

    if (
        parsed.username
        or parsed.password
    ):
        return None

    # Result images do not need arbitrary
    # ports in V2.
    if parsed.port not in {
        None,
        443,
    }:
        return None

    return value


def _host_is_public(
    hostname,
):
    try:
        addresses = socket.getaddrinfo(
            hostname,
            443,
            type=socket.SOCK_STREAM,
        )

    except socket.gaierror:
        return False

    if not addresses:
        return False

    for address in addresses:
        ip_text = address[4][0]

        try:
            ip_value = (
                ipaddress.ip_address(
                    ip_text
                )
            )

        except ValueError:
            return False

        if not ip_value.is_global:
            return False

    return True


def _looks_like_image(
    content,
):
    if not content:
        return False

    if content.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        return True

    if content.startswith(
        b"\xff\xd8\xff"
    ):
        return True

    if content.startswith(
        b"GIF87a"
    ):
        return True

    if content.startswith(
        b"GIF89a"
    ):
        return True

    if (
        len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP"
    ):
        return True

    return False


def _cache_get(
    url,
):
    return _IMAGE_CACHE.get(url)


def _cache_put(
    url,
    content,
):
    if url in _IMAGE_CACHE:
        return

    _IMAGE_CACHE[url] = content
    _IMAGE_CACHE_ORDER.append(url)

    while (
        len(_IMAGE_CACHE_ORDER)
        > MAX_MEMORY_CACHE_ITEMS
    ):
        oldest_url = (
            _IMAGE_CACHE_ORDER.pop(0)
        )
        _IMAGE_CACHE.pop(
            oldest_url,
            None,
        )


def _download_image(
    original_url,
):
    current_url = _safe_https_url(
        original_url
    )

    if current_url is None:
        raise ValueError(
            "Unsafe image URL."
        )

    cached = _cache_get(
        current_url
    )

    if cached is not None:
        return cached

    session = requests.Session()

    # Do not silently inherit proxy credentials
    # from an unrelated environment.
    session.trust_env = False

    try:
        for _ in range(
            MAX_REDIRECTS + 1
        ):
            parsed = urlparse(
                current_url
            )

            if not _host_is_public(
                parsed.hostname
            ):
                raise ValueError(
                    "Image host is not public."
                )

            response = session.get(
                current_url,
                stream=True,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": (
                        "Bekki/2.0 "
                        "ResultImageLoader"
                    ),
                    "Accept": (
                        "image/avif,"
                        "image/webp,"
                        "image/png,"
                        "image/jpeg,"
                        "image/gif"
                    ),
                },
            )

            if response.status_code in {
                301,
                302,
                303,
                307,
                308,
            }:
                redirect_target = (
                    response.headers.get(
                        "Location",
                        "",
                    )
                )

                response.close()

                current_url = (
                    _safe_https_url(
                        urljoin(
                            current_url,
                            redirect_target,
                        )
                    )
                )

                if current_url is None:
                    raise ValueError(
                        "Unsafe image redirect."
                    )

                continue

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
                .split(";")[0]
                .strip()
                .lower()
            )

            if not content_type.startswith(
                "image/"
            ):
                raise ValueError(
                    "Remote content is not an image."
                )

            content_length = (
                response.headers.get(
                    "Content-Length"
                )
            )

            if content_length:
                try:
                    declared_size = int(
                        content_length
                    )

                except ValueError:
                    declared_size = 0

                if (
                    declared_size
                    > MAX_IMAGE_BYTES
                ):
                    raise ValueError(
                        "Remote image is too large."
                    )

            chunks = []
            total_size = 0

            for chunk in (
                response.iter_content(
                    chunk_size=64 * 1024
                )
            ):
                if not chunk:
                    continue

                total_size += len(chunk)

                if (
                    total_size
                    > MAX_IMAGE_BYTES
                ):
                    raise ValueError(
                        "Remote image is too large."
                    )

                chunks.append(chunk)

            content = b"".join(
                chunks
            )

            if not _looks_like_image(
                content
            ):
                raise ValueError(
                    "Downloaded data is not "
                    "a supported image."
                )

            _cache_put(
                original_url,
                content,
            )

            return content

        raise ValueError(
            "Too many image redirects."
        )

    finally:
        session.close()


class ImageLoadSignals(QObject):
    loaded = Signal(
        str,
        bytes,
    )

    failed = Signal(
        str,
        str,
    )


class ImageLoadJob(QRunnable):
    def __init__(
        self,
        url,
    ):
        super().__init__()

        self.url = url
        self.signals = (
            ImageLoadSignals()
        )

    def run(self):
        try:
            content = _download_image(
                self.url
            )

            self.signals.loaded.emit(
                self.url,
                content,
            )

        except Exception as error:
            self.signals.failed.emit(
                self.url,
                str(error),
            )


def load_image_async(
    url,
    loaded_handler,
    failed_handler=None,
):
    """Load one image without blocking Qt's UI thread."""

    safe_url = _safe_https_url(
        url
    )

    if safe_url is None:
        if failed_handler:
            failed_handler(
                url,
                "Unsafe image URL.",
            )

        return None

    cached = _cache_get(
        safe_url
    )

    if cached is not None:
        loaded_handler(
            safe_url,
            cached,
        )

        return None

    job = ImageLoadJob(
        safe_url
    )

    job.signals.loaded.connect(
        loaded_handler
    )

    if failed_handler:
        job.signals.failed.connect(
            failed_handler
        )

    QThreadPool.globalInstance().start(
        job
    )

    return job