"""Immutable source and visual evidence records for Bekki Knowledge.

The Knowledge ledger remains a JSON document stored authoritatively in
SQLite.  Public source images are content-addressed files beside that store;
SQLite keeps their portable metadata and every claim keeps only asset IDs.
Private local/user images are deliberately outside this automatic path.
"""

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import sqlite_storage


KNOWLEDGE_EVIDENCE_CONTRACT_VERSION = 1
KNOWLEDGE_MEDIA_INDEX_VERSION = 1
MAX_EVIDENCE_RECORDS = 16
MAX_TEXT_EXCERPT_CHARS = 2400
MAX_VISUAL_OBSERVATION_CHARS = 1200
MAX_IMAGES_PER_CLAIM = 2
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_ENCODED_IMAGE_CHARS = 12 * 1024 * 1024
MAX_MEDIA_ASSETS = 512

_SAFE_ASSET_ID = re.compile(r"^media_[0-9a-f]{24}$")
_MEDIA_LOCK = threading.RLock()
_SUPPORTED_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _digest_bytes(_canonical(value).encode("utf-8"))


def _bounded_text(value, maximum):
    return " ".join(str(value or "").split())[:maximum]


def _normalized_evidence_text(value):
    return " ".join(str(value or "").split()).casefold()


def _source_domain(source):
    source = source if isinstance(source, dict) else {}
    domain = _bounded_text(source.get("domain"), 200).lower()
    if domain:
        return domain.removeprefix("www.")
    return urlparse(str(source.get("url") or "")).netloc.lower().removeprefix(
        "www."
    )[:200]


def _public_source(source):
    source = source if isinstance(source, dict) else {}
    privacy_class = str(source.get("privacy_class") or "").upper().strip()
    if privacy_class and privacy_class != "PUBLIC_SOURCE":
        return False
    source_origin = str(
        source.get("source_origin") or source.get("origin") or ""
    ).upper().strip()
    if source.get("user_supplied") is True or source_origin in {
        "USER_UPLOAD", "USER_ATTACHMENT", "LOCAL_FILE", "PRIVATE_MEDIA",
    }:
        return False
    url = str(source.get("url") or "").strip()
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _portable_image_url(value):
    """Retain an auditable HTTPS locator without credentials or query tokens."""

    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        return ""
    hostname = parsed.hostname.lower()
    if (
        hostname == "localhost"
        or hostname.endswith((".local", ".internal", ".localhost"))
    ):
        return ""
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return ""
    except ValueError:
        pass
    return parsed._replace(params="", query="", fragment="").geturl()[:2000]


def compact_source(source):
    """Return portable public-source identity without page bodies or images."""

    source = source if isinstance(source, dict) else {}
    url = str(source.get("url") or "").strip()[:2000]
    domain = _source_domain(source)
    title = _bounded_text(
        source.get("title") or source.get("name") or domain,
        300,
    )
    identity = url or (domain + "\n" + title)
    return {
        "source_id": "source_" + _digest_bytes(identity.encode("utf-8"))[:24],
        "title": title,
        "url": url,
        "domain": domain,
        "published_at": _bounded_text(
            source.get("published_at") or source.get("published"), 100
        ) or None,
        "source_score": source.get("source_score", source.get("trust_score")),
    }


def _media_index_file(data_dir):
    return os.path.join(str(data_dir), "knowledge", "media", "index.json")


def _media_assets_dir(data_dir):
    return os.path.join(str(data_dir), "knowledge", "media", "assets")


def _empty_media_index():
    return {
        "schema_version": KNOWLEDGE_MEDIA_INDEX_VERSION,
        "revision": 0,
        "updated_at": None,
        "assets": {},
    }


def _load_media_index(data_dir):
    path = _media_index_file(data_dir)
    value = sqlite_storage.load_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        _empty_media_index(),
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )
    if not isinstance(value, dict):
        return _empty_media_index()
    assets = value.get("assets")
    value["assets"] = assets if isinstance(assets, dict) else {}
    value["schema_version"] = KNOWLEDGE_MEDIA_INDEX_VERSION
    return value


def _save_media_index(data_dir, value):
    path = _media_index_file(data_dir)
    sqlite_storage.save_document(
        "knowledge",
        sqlite_storage.document_key_for(path),
        path,
        value,
        migration_backup_suffix=(
            sqlite_storage.PHASE_TWO_MIGRATION_BACKUP_SUFFIX
        ),
    )


def initialize(data_dir="data"):
    os.makedirs(_media_assets_dir(data_dir), exist_ok=True)
    return _load_media_index(data_dir)


def load_media_index(data_dir="data"):
    return deepcopy(_load_media_index(data_dir))


def _decode_image_payload(value):
    text = str(value or "").strip()
    if not text or len(text) > MAX_ENCODED_IMAGE_CHARS:
        return None
    if text.startswith("data:"):
        marker = text.find(",")
        if marker < 0 or ";base64" not in text[:marker].lower():
            return None
        text = text[marker + 1:]
    try:
        payload = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not 0 < len(payload) <= MAX_IMAGE_BYTES:
        return None
    for signature, mime_type, extension in _SUPPORTED_SIGNATURES:
        if payload.startswith(signature):
            return payload, mime_type, extension
    if (
        len(payload) >= 12
        and payload[:4] == b"RIFF"
        and payload[8:12] == b"WEBP"
    ):
        return payload, "image/webp", ".webp"
    return None


def _write_asset_file(data_dir, asset_id, extension, payload):
    assets_dir = Path(_media_assets_dir(data_dir))
    assets_dir.mkdir(parents=True, exist_ok=True)
    destination = assets_dir / (asset_id + extension)
    if destination.exists():
        try:
            if _digest_bytes(destination.read_bytes()) == _digest_bytes(payload):
                return destination
        except OSError:
            pass
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + asset_id + ".",
        suffix=".tmp",
        dir=str(assets_dir),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination


def _store_public_images_unlocked(
    source,
    image_payloads,
    image_labels=None,
    selected_indexes=None,
    *,
    image_urls=None,
    data_dir="data",
):
    """Cache selected source-bound images and return portable asset metadata."""

    source = source if isinstance(source, dict) else {}
    if not _public_source(source):
        return []
    payloads = image_payloads if isinstance(image_payloads, list) else []
    labels = image_labels if isinstance(image_labels, list) else []
    urls = image_urls if isinstance(image_urls, list) else []
    indexes = []
    for raw in selected_indexes or []:
        if isinstance(raw, bool):
            continue
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(payloads) and index not in indexes:
            indexes.append(index)
        if len(indexes) >= MAX_IMAGES_PER_CLAIM:
            break
    if not indexes:
        return []

    source_info = compact_source(source)
    index_payload = initialize(data_dir)
    assets = index_payload.setdefault("assets", {})
    stored = []
    changed = False
    for index in indexes:
        decoded = _decode_image_payload(payloads[index - 1])
        if decoded is None:
            continue
        payload, mime_type, extension = decoded
        sha256 = _digest_bytes(payload)
        asset_id = "media_" + sha256[:24]
        old = assets.get(asset_id)
        if not isinstance(old, dict) and len(assets) >= MAX_MEDIA_ASSETS:
            continue
        destination = _write_asset_file(
            data_dir, asset_id, extension, payload
        )
        relative_path = destination.relative_to(Path(data_dir)).as_posix()
        label = _bounded_text(
            labels[index - 1] if index - 1 < len(labels) else "",
            120,
        )
        metadata = {
            "asset_id": asset_id,
            "sha256": sha256,
            "mime_type": mime_type,
            "byte_length": len(payload),
            "relative_path": relative_path,
            "source": source_info,
            "sources": [source_info],
            "source_image_index": index,
            "source_image_label": label,
            "source_image_url": (
                _portable_image_url(urls[index - 1])
                if index - 1 < len(urls) else ""
            ) or None,
            "captured_at": _now_iso(),
            "privacy_class": "PUBLIC_SOURCE",
        }
        if not isinstance(old, dict):
            assets[asset_id] = metadata
            changed = True
        else:
            metadata = deepcopy(old)
            known_sources = [
                value for value in metadata.get("sources", [])
                if isinstance(value, dict)
            ]
            if not known_sources and isinstance(metadata.get("source"), dict):
                known_sources = [metadata["source"]]
            if source_info.get("source_id") not in {
                value.get("source_id") for value in known_sources
            } and len(known_sources) < 8:
                known_sources.append(source_info)
                metadata["sources"] = known_sources
                assets[asset_id] = metadata
                changed = True
        stored.append(metadata)
    if changed:
        index_payload["revision"] = int(index_payload.get("revision") or 0) + 1
        index_payload["updated_at"] = _now_iso()
        _save_media_index(data_dir, index_payload)
    return stored


def store_public_images(
    source,
    image_payloads,
    image_labels=None,
    selected_indexes=None,
    *,
    image_urls=None,
    data_dir="data",
):
    """Serialize one process's file-plus-index media transaction."""

    with _MEDIA_LOCK:
        return _store_public_images_unlocked(
            source,
            image_payloads,
            image_labels,
            selected_indexes,
            image_urls=image_urls,
            data_dir=data_dir,
        )


def text_evidence_seed(source, page_text, excerpt):
    """Build one source-snapshot record only for a literal page excerpt."""

    source = source if isinstance(source, dict) else {}
    page_text = str(page_text or "")
    excerpt = _bounded_text(excerpt, MAX_TEXT_EXCERPT_CHARS)
    if not _public_source(source) or not excerpt:
        return None
    if _normalized_evidence_text(excerpt) not in _normalized_evidence_text(
        page_text
    ):
        return None
    source_info = compact_source(source)
    record = {
        "modality": "TEXT",
        "support_kind": "LITERAL_SOURCE_EXCERPT",
        "source": source_info,
        "source_snapshot_sha256": _digest_bytes(page_text.encode("utf-8")),
        "excerpt": excerpt,
        "excerpt_sha256": _digest_bytes(excerpt.encode("utf-8")),
        "locator": {"kind": "PAGE_TEXT"},
    }
    record["evidence_id"] = "evidence_" + _digest(record)[:24]
    return {
        "contract_version": KNOWLEDGE_EVIDENCE_CONTRACT_VERSION,
        "records": [record],
    }


def autonomous_evidence_seed(
    source,
    page_text,
    candidate,
    page_images=None,
    page_image_labels=None,
    page_image_urls=None,
):
    """Bind one autonomous candidate to literal text and selected page images.

    Autonomous learning deliberately keeps literal source text as a mandatory
    anchor. A visual observation can supplement that anchor, but can never
    create an image-only reusable fact.
    """

    candidate = candidate if isinstance(candidate, dict) else {}
    seed = text_evidence_seed(
        source, page_text, candidate.get("evidence_excerpt")
    )
    if seed is None:
        seed = text_evidence_seed(source, page_text, candidate.get("claim"))
    if seed is None:
        return None

    evidence = _normalized_extraction_evidence(candidate)
    if evidence["modality"] not in {"IMAGE", "TEXT_AND_IMAGE"}:
        return seed
    if not evidence["visual_observation"]:
        return seed

    payloads = [
        str(value or "")
        for value in (page_images if isinstance(page_images, list) else [])[
            :MAX_IMAGES_PER_CLAIM
        ]
    ]
    labels = [
        _bounded_text(value, 120)
        for value in (
            page_image_labels if isinstance(page_image_labels, list) else []
        )[:len(payloads)]
    ]
    urls = [
        _portable_image_url(value)
        for value in (
            page_image_urls if isinstance(page_image_urls, list) else []
        )[:len(payloads)]
    ]
    indexes = [
        index
        for index in evidence["image_indexes"]
        if 1 <= index <= len(payloads)
        and _decode_image_payload(payloads[index - 1]) is not None
    ][:MAX_IMAGES_PER_CLAIM]
    if not indexes:
        return seed

    source_info = compact_source(source)
    record = {
        "modality": "IMAGE",
        "support_kind": "SOURCE_BOUND_VISUAL_OBSERVATION",
        "source": source_info,
        "source_snapshot_sha256": _digest_bytes(
            str(page_text or "").encode("utf-8")
        ),
        "visual_observation": evidence["visual_observation"],
        "image_indexes": indexes,
        "image_labels": labels,
        "image_urls": urls,
        "_image_payloads": payloads,
        "locator": {"kind": "SOURCE_IMAGE"},
    }
    record["evidence_id"] = "evidence_" + _digest(record)[:24]
    seed["records"].append(record)
    return seed


def seed_fingerprint(seed):
    seed = seed if isinstance(seed, dict) else {}
    records = [
        value for value in seed.get("records", [])
        if isinstance(value, dict)
    ]
    return _digest({
        "contract_version": KNOWLEDGE_EVIDENCE_CONTRACT_VERSION,
        "records": records,
    }) if records else ""


def _normalized_extraction_evidence(answer_item):
    answer_item = answer_item if isinstance(answer_item, dict) else {}
    raw = answer_item.get("evidence")
    raw = raw if isinstance(raw, dict) else {}
    modality = str(raw.get("modality") or "").upper().strip()
    if modality not in {"TEXT", "IMAGE", "TEXT_AND_IMAGE", "NONE"}:
        modality = ""
    indexes = []
    for value in raw.get("image_indexes", []):
        if isinstance(value, bool):
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 2 and value not in indexes:
            indexes.append(value)
    return {
        "modality": modality,
        "text_excerpt": _bounded_text(
            raw.get("text_excerpt"), MAX_TEXT_EXCERPT_CHARS
        ),
        "image_indexes": indexes[:MAX_IMAGES_PER_CLAIM],
        "visual_observation": _bounded_text(
            raw.get("visual_observation"), MAX_VISUAL_OBSERVATION_CHARS
        ),
    }


def _search_answer_records(search_result, accepted_only):
    rows = []
    for value in (search_result or {}).get("answers", []):
        if not isinstance(value, dict):
            continue
        if accepted_only and value.get("accepted") is not True:
            continue
        answer = value.get("answer")
        if answer in (None, "", [], {}):
            continue
        rows.append(value)
    return rows[:8]


def search_result_evidence_seed(search_result, *, accepted_only=True):
    """Build immutable records from source-indexed accepted extraction data."""

    search_result = search_result if isinstance(search_result, dict) else {}
    results = [
        value for value in search_result.get("results", [])
        if isinstance(value, dict)
    ]
    records = []
    for answer_item in _search_answer_records(search_result, accepted_only):
        try:
            source_index = int(answer_item.get("index") or 0)
        except (TypeError, ValueError):
            source_index = 0
        if not 1 <= source_index <= len(results):
            continue
        source = results[source_index - 1]
        if source.get("page_success") is not True or not _public_source(source):
            continue
        page_text = str(source.get("page_content") or "")
        source_info = compact_source(source)
        extracted = _bounded_text(
            answer_item.get("answer"), MAX_TEXT_EXCERPT_CHARS
        )
        evidence = _normalized_extraction_evidence(answer_item)
        excerpt = evidence["text_excerpt"]
        if not excerpt and extracted and (
            _normalized_evidence_text(extracted)
            in _normalized_evidence_text(page_text)
        ):
            excerpt = extracted
        if excerpt and (
            _normalized_evidence_text(excerpt)
            in _normalized_evidence_text(page_text)
        ):
            record = {
                "modality": "TEXT",
                "support_kind": "LITERAL_SOURCE_EXCERPT",
                "source": source_info,
                "source_snapshot_sha256": _digest_bytes(
                    page_text.encode("utf-8")
                ),
                "excerpt": excerpt,
                "excerpt_sha256": _digest_bytes(excerpt.encode("utf-8")),
                "locator": {"kind": "PAGE_TEXT", "source_index": source_index},
            }
            record["evidence_id"] = "evidence_" + _digest(record)[:24]
            records.append(record)
        elif extracted and evidence["modality"] in {"TEXT", "TEXT_AND_IMAGE"}:
            record = {
                "modality": "TEXT",
                "support_kind": "SOURCE_BOUND_EXTRACTION",
                "source": source_info,
                "source_snapshot_sha256": _digest_bytes(
                    page_text.encode("utf-8")
                ),
                "extracted_answer": extracted,
                "extracted_answer_sha256": _digest_bytes(
                    extracted.encode("utf-8")
                ),
                "locator": {"kind": "PAGE_EXTRACTION", "source_index": source_index},
            }
            record["evidence_id"] = "evidence_" + _digest(record)[:24]
            records.append(record)

        if (
            evidence["modality"] in {"IMAGE", "TEXT_AND_IMAGE"}
            and evidence["visual_observation"]
            and evidence["image_indexes"]
        ):
            records.append({
                "modality": "IMAGE",
                "support_kind": "SOURCE_BOUND_VISUAL_OBSERVATION",
                "source": source_info,
                "source_snapshot_sha256": _digest_bytes(
                    page_text.encode("utf-8")
                ),
                "visual_observation": evidence["visual_observation"],
                "image_indexes": evidence["image_indexes"],
                "image_labels": [
                    _bounded_text(value, 120)
                    for value in source.get("page_image_labels", [])[:2]
                ] if isinstance(source.get("page_image_labels"), list) else [],
                "image_urls": [
                    _portable_image_url(value)
                    for value in source.get("page_image_urls", [])[:2]
                ] if isinstance(source.get("page_image_urls"), list) else [],
                "_image_payloads": [
                    str(value or "")
                    for value in source.get("page_images", [])[:2]
                ] if isinstance(source.get("page_images"), list) else [],
                "locator": {"kind": "SOURCE_IMAGE", "source_index": source_index},
            })
        if len(records) >= MAX_EVIDENCE_RECORDS:
            break
    return {
        "contract_version": KNOWLEDGE_EVIDENCE_CONTRACT_VERSION,
        "records": records[:MAX_EVIDENCE_RECORDS],
    } if records else {}


def finalize_bundle(claim_id, seed, *, data_dir="data"):
    """Persist public image payloads and seal a portable claim evidence bundle."""

    seed = seed if isinstance(seed, dict) else {}
    records = []
    seen = set()
    for raw in seed.get("records", [])[:MAX_EVIDENCE_RECORDS]:
        if not isinstance(raw, dict):
            continue
        record = deepcopy(raw)
        payloads = record.pop("_image_payloads", [])
        if record.get("modality") == "IMAGE":
            image_urls = record.pop("image_urls", [])
            stored = store_public_images(
                record.get("source"),
                payloads,
                record.get("image_labels"),
                record.pop("image_indexes", []),
                image_urls=image_urls,
                data_dir=data_dir,
            )
            asset_ids = [
                value.get("asset_id") for value in stored
                if isinstance(value, dict) and value.get("asset_id")
            ]
            if not asset_ids:
                continue
            record["asset_ids"] = asset_ids
            record["asset_sha256"] = [value.get("sha256") for value in stored]
        record.pop("image_labels", None)
        record["contract_version"] = KNOWLEDGE_EVIDENCE_CONTRACT_VERSION
        record.pop("evidence_id", None)
        record["evidence_id"] = "evidence_" + _digest(record)[:24]
        evidence_id = record["evidence_id"]
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        records.append(record)
    if not records:
        return {}
    core = {
        "contract_version": KNOWLEDGE_EVIDENCE_CONTRACT_VERSION,
        "claim_id": str(claim_id or "")[:160],
        "records": records,
        "modalities": sorted({
            str(value.get("modality") or "") for value in records
            if str(value.get("modality") or "")
        }),
        "source_bound": all(
            _public_source(value.get("source")) for value in records
        ),
    }
    core["fingerprint"] = _digest(core)
    return core


def merge_bundles(claim_id, *bundles):
    records = []
    seen = set()
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        for record in bundle.get("records", []):
            if not isinstance(record, dict):
                continue
            evidence_id = str(record.get("evidence_id") or "")
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(evidence_id)
            records.append(deepcopy(record))
            if len(records) >= MAX_EVIDENCE_RECORDS:
                break
        if len(records) >= MAX_EVIDENCE_RECORDS:
            break
    if not records:
        return {}
    core = {
        "contract_version": KNOWLEDGE_EVIDENCE_CONTRACT_VERSION,
        "claim_id": str(claim_id or "")[:160],
        "records": records,
        "modalities": sorted({
            str(value.get("modality") or "") for value in records
            if str(value.get("modality") or "")
        }),
        "source_bound": all(
            _public_source(value.get("source")) for value in records
        ),
    }
    core["fingerprint"] = _digest(core)
    return core


def bundle_summary(bundle):
    bundle = bundle if isinstance(bundle, dict) else {}
    records = [
        value for value in bundle.get("records", [])
        if isinstance(value, dict)
    ]
    return {
        "contract_version": bundle.get("contract_version"),
        "fingerprint": str(bundle.get("fingerprint") or "")[:64],
        "modalities": [
            str(value)[:20] for value in bundle.get("modalities", [])[:4]
        ],
        "source_count": len({
            str((value.get("source") or {}).get("source_id") or "")
            for value in records
            if isinstance(value.get("source"), dict)
        } - {""}),
        "visual_asset_ids": [
            str(asset_id)[:80]
            for value in records
            for asset_id in value.get("asset_ids", [])
            if str(asset_id)
        ][:8],
        "visual_observations": [
            _bounded_text(value.get("visual_observation"), 500)
            for value in records
            if value.get("modality") == "IMAGE"
            and _bounded_text(value.get("visual_observation"), 500)
        ][:4],
        "text_support": [
            _bounded_text(
                value.get("excerpt") or value.get("extracted_answer"),
                700,
            )
            for value in records
            if value.get("modality") == "TEXT"
            and _bounded_text(
                value.get("excerpt") or value.get("extracted_answer"),
                700,
            )
        ][:4],
    }


def validate_bundle(bundle, media_assets=None):
    """Return structural/hash failures without mutating any store."""

    failures = []
    bundle = bundle if isinstance(bundle, dict) else {}
    if bundle.get("contract_version") != KNOWLEDGE_EVIDENCE_CONTRACT_VERSION:
        return ["contract_version_invalid"]
    if not str(bundle.get("claim_id") or "").strip():
        failures.append("claim_id_missing")
    records = bundle.get("records")
    if not isinstance(records, list) or not records:
        return ["records_missing"]
    if len(records) > MAX_EVIDENCE_RECORDS:
        failures.append("records_unbounded")
    clean_records = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            failures.append("record_invalid:" + str(index))
            continue
        value = deepcopy(record)
        evidence_id = str(value.pop("evidence_id", ""))
        expected_id = "evidence_" + _digest(value)[:24]
        if evidence_id != expected_id:
            failures.append("evidence_hash_invalid:" + str(index))
        modality = str(record.get("modality") or "")
        if modality not in {"TEXT", "IMAGE"}:
            failures.append("modality_invalid:" + str(index))
        source = record.get("source")
        source = source if isinstance(source, dict) else {}
        if not _public_source(source):
            failures.append("source_not_public:" + str(index))
        elif source.get("source_id") != compact_source(source).get("source_id"):
            failures.append("source_id_invalid:" + str(index))
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(record.get("source_snapshot_sha256") or ""),
        ):
            failures.append("source_snapshot_hash_invalid:" + str(index))
        if record.get("contract_version") != (
            KNOWLEDGE_EVIDENCE_CONTRACT_VERSION
        ):
            failures.append("record_contract_version_invalid:" + str(index))
        if not isinstance(record.get("locator"), dict):
            failures.append("locator_invalid:" + str(index))
        if modality == "TEXT":
            if record.get("support_kind") not in {
                "LITERAL_SOURCE_EXCERPT", "SOURCE_BOUND_EXTRACTION",
            }:
                failures.append("text_support_kind_invalid:" + str(index))
            excerpt = str(record.get("excerpt") or "")
            extracted = str(record.get("extracted_answer") or "")
            if not excerpt and not extracted:
                failures.append("text_support_missing:" + str(index))
            if excerpt and record.get("excerpt_sha256") != _digest_bytes(
                excerpt.encode("utf-8")
            ):
                failures.append("excerpt_hash_invalid:" + str(index))
            if extracted and record.get(
                "extracted_answer_sha256"
            ) != _digest_bytes(extracted.encode("utf-8")):
                failures.append("extraction_hash_invalid:" + str(index))
        if modality == "IMAGE":
            if record.get("support_kind") != (
                "SOURCE_BOUND_VISUAL_OBSERVATION"
            ):
                failures.append("image_support_kind_invalid:" + str(index))
            if not str(record.get("visual_observation") or "").strip():
                failures.append("visual_observation_missing:" + str(index))
            asset_ids = record.get("asset_ids")
            asset_hashes = record.get("asset_sha256")
            if not isinstance(asset_ids, list) or not asset_ids:
                failures.append("asset_ids_missing:" + str(index))
                asset_ids = []
            if (
                not isinstance(asset_hashes, list)
                or len(asset_hashes) != len(asset_ids)
            ):
                failures.append("asset_hashes_invalid:" + str(index))
                asset_hashes = []
            for position, asset_id in enumerate(asset_ids):
                if not _SAFE_ASSET_ID.fullmatch(str(asset_id or "")):
                    failures.append("asset_id_invalid:" + str(index))
                elif isinstance(media_assets, dict) and asset_id not in media_assets:
                    failures.append("asset_missing:" + str(asset_id))
                if position < len(asset_hashes) and not re.fullmatch(
                    r"[0-9a-f]{64}", str(asset_hashes[position] or "")
                ):
                    failures.append("asset_hash_invalid:" + str(index))
        clean_records.append(record)
    core = {
        "contract_version": bundle.get("contract_version"),
        "claim_id": str(bundle.get("claim_id") or "")[:160],
        "records": clean_records,
        "modalities": sorted({
            str(value.get("modality") or "") for value in clean_records
            if str(value.get("modality") or "")
        }),
        "source_bound": all(
            _public_source(value.get("source")) for value in clean_records
        ),
    }
    if bundle.get("fingerprint") != _digest(core):
        failures.append("bundle_hash_invalid")
    if bundle.get("modalities") != core["modalities"]:
        failures.append("modalities_invalid")
    if bundle.get("source_bound") is not core["source_bound"]:
        failures.append("source_bound_invalid")
    return failures


def audit_evidence_store(
    items,
    *,
    data_dir="data",
    media_index=None,
    verify_files=True,
):
    """Audit claim bundles and their content-addressed public media assets."""

    index = (
        deepcopy(media_index)
        if isinstance(media_index, dict)
        else load_media_index(data_dir)
    )
    assets = index.get("assets")
    assets = assets if isinstance(assets, dict) else {}
    counts = {
        "claims": 0,
        "contract_current": 0,
        "legacy_compatible": 0,
        "text_claims": 0,
        "image_claims": 0,
        "media_assets": len(assets),
        "referenced_assets": 0,
        "orphan_assets": 0,
    }
    failures = []
    referenced = set()

    def fail(label):
        label = str(label)
        if label not in failures:
            failures.append(label)

    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").lower() not in {
            "verified", "disputed"
        }:
            continue
        counts["claims"] += 1
        knowledge_id = str(item.get("id") or "unknown")
        bundle = item.get("evidence_bundle")
        if not isinstance(bundle, dict) or not bundle:
            counts["legacy_compatible"] += 1
            continue
        counts["contract_current"] += 1
        if str(bundle.get("claim_id") or "") != knowledge_id:
            fail(knowledge_id + ":claim_id_mismatch")
        for code in validate_bundle(bundle, assets):
            fail(knowledge_id + ":" + code)
        modalities = set(bundle.get("modalities") or [])
        if "TEXT" in modalities:
            counts["text_claims"] += 1
        if "IMAGE" in modalities:
            counts["image_claims"] += 1
        for record in bundle.get("records", []):
            if not isinstance(record, dict) or record.get("modality") != "IMAGE":
                continue
            asset_ids = record.get("asset_ids")
            asset_ids = asset_ids if isinstance(asset_ids, list) else []
            expected_hashes = record.get("asset_sha256")
            expected_hashes = (
                expected_hashes if isinstance(expected_hashes, list) else []
            )
            for position, asset_id in enumerate(asset_ids):
                asset_id = str(asset_id or "")
                referenced.add(asset_id)
                metadata = assets.get(asset_id)
                if not isinstance(metadata, dict):
                    continue
                if position < len(expected_hashes) and str(
                    expected_hashes[position] or ""
                ) != str(metadata.get("sha256") or ""):
                    fail(knowledge_id + ":asset_record_hash_mismatch:" + asset_id)

    counts["referenced_assets"] = len(referenced)
    counts["orphan_assets"] = len(set(assets) - referenced)
    if assets and index.get("schema_version") != KNOWLEDGE_MEDIA_INDEX_VERSION:
        fail("media_index:contract_version_invalid")

    root = Path(data_dir).resolve()
    for asset_id, metadata in assets.items():
        asset_id = str(asset_id or "")
        if not _SAFE_ASSET_ID.fullmatch(asset_id):
            fail("media_index:asset_id_invalid:" + asset_id)
            continue
        if not isinstance(metadata, dict):
            fail("media_index:metadata_invalid:" + asset_id)
            continue
        if str(metadata.get("asset_id") or "") != asset_id:
            fail("media_index:metadata_id_mismatch:" + asset_id)
        if metadata.get("privacy_class") != "PUBLIC_SOURCE":
            fail("media_index:privacy_class_invalid:" + asset_id)
        if not _public_source(metadata.get("source")):
            fail("media_index:source_not_public:" + asset_id)
        sha256 = str(metadata.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            fail("media_index:sha256_invalid:" + asset_id)
        elif asset_id != "media_" + sha256[:24]:
            fail("media_index:content_address_invalid:" + asset_id)
        relative = str(metadata.get("relative_path") or "")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            fail("media_index:path_escape:" + asset_id)
            continue
        if not verify_files:
            continue
        if not path.is_file():
            fail("media_index:file_missing:" + asset_id)
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            fail("media_index:file_unreadable:" + asset_id)
            continue
        if _digest_bytes(payload) != sha256:
            fail("media_index:file_hash_invalid:" + asset_id)
        try:
            byte_length = int(metadata.get("byte_length"))
        except (TypeError, ValueError):
            byte_length = -1
        if byte_length != len(payload):
            fail("media_index:file_size_invalid:" + asset_id)
        decoded = None
        for signature, mime_type, extension in _SUPPORTED_SIGNATURES:
            if payload.startswith(signature):
                decoded = (mime_type, extension)
                break
        if (
            decoded is None
            and len(payload) >= 12
            and payload[:4] == b"RIFF"
            and payload[8:12] == b"WEBP"
        ):
            decoded = ("image/webp", ".webp")
        if decoded is None:
            fail("media_index:file_type_invalid:" + asset_id)
        else:
            mime_type, extension = decoded
            if metadata.get("mime_type") != mime_type:
                fail("media_index:mime_type_invalid:" + asset_id)
            if path.suffix.lower() != extension:
                fail("media_index:file_extension_invalid:" + asset_id)

    return {"counts": counts, "failures": failures}


def media_index_document_required(evidence_audit):
    """Require the SQLite media index only when image lineage depends on it.

    Before the first V1.10.54.5 runtime start, an existing installation can
    legitimately contain only legacy or text-only claims and no media-index
    document. ``initialize`` creates the empty document on first use. Image
    claims, referenced assets, or stored assets still fail closed and require
    the authoritative index to be present.
    """

    audit = evidence_audit if isinstance(evidence_audit, dict) else {}
    counts = audit.get("counts")
    counts = counts if isinstance(counts, dict) else {}
    for key in ("image_claims", "referenced_assets", "media_assets"):
        try:
            if int(counts.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def resolve_asset_path(asset_id, *, data_dir="data"):
    if not _SAFE_ASSET_ID.fullmatch(str(asset_id or "")):
        return None
    index = _load_media_index(data_dir)
    metadata = index.get("assets", {}).get(asset_id)
    if not isinstance(metadata, dict):
        return None
    relative = str(metadata.get("relative_path") or "")
    root = Path(data_dir).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return str(path) if path.is_file() else None


def load_verified_public_image(
    asset_id,
    *,
    expected_sha256,
    data_dir="data",
):
    """Read one content-addressed public image only when every seal matches.

    This is the sole read path used by Knowledge visual recall.  It never
    repairs metadata, follows a remote URL, or returns a path to the model.
    Any structural, privacy, size, type, or hash mismatch fails closed.
    """

    asset_id = str(asset_id or "").strip()
    if not _SAFE_ASSET_ID.fullmatch(asset_id):
        return None
    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        return None

    index = _load_media_index(data_dir)
    metadata = index.get("assets", {}).get(asset_id)
    if not isinstance(metadata, dict):
        return None
    if metadata.get("privacy_class") != "PUBLIC_SOURCE":
        return None
    if not _public_source(metadata.get("source")):
        return None

    sha256 = str(metadata.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return None
    if asset_id != "media_" + sha256[:24]:
        return None
    if expected_sha256 != sha256:
        return None

    relative = str(metadata.get("relative_path") or "")
    root = Path(data_dir).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not 0 < len(payload) <= MAX_IMAGE_BYTES:
        return None
    if _digest_bytes(payload) != sha256:
        return None
    try:
        if int(metadata.get("byte_length")) != len(payload):
            return None
    except (TypeError, ValueError):
        return None

    detected = None
    for signature, mime_type, extension in _SUPPORTED_SIGNATURES:
        if payload.startswith(signature):
            detected = (mime_type, extension)
            break
    if (
        detected is None
        and len(payload) >= 12
        and payload[:4] == b"RIFF"
        and payload[8:12] == b"WEBP"
    ):
        detected = ("image/webp", ".webp")
    if detected is None:
        return None
    mime_type, extension = detected
    if metadata.get("mime_type") != mime_type:
        return None
    if path.suffix.lower() != extension:
        return None

    return {
        "asset_id": asset_id,
        "sha256": sha256,
        "mime_type": mime_type,
        "byte_length": len(payload),
        "payload": payload,
        "source": deepcopy(metadata.get("source")),
        "source_image_label": _bounded_text(
            metadata.get("source_image_label"), 120
        ),
    }
