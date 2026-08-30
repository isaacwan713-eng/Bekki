"""Verified reusable device skills with a fail-closed V2 lifecycle."""

import hashlib
import json
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone


DATA_DIR = "data"
SKILLS_FILE = os.path.join(DATA_DIR, "skills.json")
PENDING_FILE = os.path.join(DATA_DIR, "pending_skills.json")
INVALIDATED_FILE = os.path.join(DATA_DIR, "invalidated_skills.json")
RUNS_FILE = os.path.join(DATA_DIR, "skill_runs.jsonl")
SCHEMA_VERSION = 2
MAX_SKILLS = 200
MAX_PENDING = 40
PENDING_TTL_HOURS = 24

ALLOWED_SKILL_SCOPES = {
    "OPEN_DESTINATION_FOLDER",
    "INSTALL_CONTENT",
}
ALLOWED_ACTIONS_BY_SCOPE = {
    "OPEN_DESTINATION_FOLDER": {"opened_fm_tactic_folder"},
    "INSTALL_CONTENT": {"installed_fm_tactic"},
}
NEGATIVE_EXECUTION_FLAGS = {
    "requires_approval",
    "needs_clarification",
    "cancelled",
    "canceled",
    "interrupted",
    "user_rejected",
    "rejected",
    "failed",
    "failure",
    "captcha",
    "human_handoff",
    "permission_denied",
    "access_denied",
    "error",
}

_REGISTRY_LOCK = threading.RLock()


class RegistryPersistenceError(RuntimeError):
    """A registry could not be read or durably written."""


class RegistryCorruptionError(RegistryPersistenceError):
    """Neither the primary JSON registry nor its backup was usable."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _backup_path(path):
    return str(path) + ".bak"


def _read_list_state(path):
    try:
        with open(path, "rb") as file:
            raw = file.read()
    except FileNotFoundError:
        return "missing", None, None
    except OSError as error:
        raise RegistryPersistenceError(
            "Could not read registry " + str(path) + ": " + str(error)
        ) from error

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "corrupt", None, raw
    if not isinstance(value, list):
        return "corrupt", None, raw
    return "valid", value, raw


def _fsync_directory(directory):
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path, payload):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    temporary = (
        str(path)
        + ".tmp."
        + str(os.getpid())
        + "."
        + uuid.uuid4().hex
    )
    try:
        with open(temporary, "xb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        _fsync_directory(directory)
    except OSError as error:
        raise RegistryPersistenceError(
            "Could not durably write registry " + str(path) + ": " + str(error)
        ) from error
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass


def _load_list(path):
    """Load a list registry, recovering from .bak and never masking corruption."""
    with _REGISTRY_LOCK:
        primary_state, primary, _primary_raw = _read_list_state(path)
        if primary_state == "valid":
            return primary

        backup = _backup_path(path)
        backup_state, backup_value, backup_raw = _read_list_state(backup)
        if backup_state == "valid":
            _atomic_write_bytes(path, backup_raw)
            return backup_value

        if primary_state == "missing" and backup_state == "missing":
            return []

        raise RegistryCorruptionError(
            "Registry and backup are unusable: " + str(path)
        )


def _save_list(path, items, maximum):
    """Durably replace a list registry while preserving one valid backup."""
    if not isinstance(items, list):
        raise TypeError("Registry payload must be a list.")
    bounded = items[-int(maximum):]
    payload = (
        json.dumps(bounded, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    with _REGISTRY_LOCK:
        primary_state, _primary_value, primary_raw = _read_list_state(path)
        backup = _backup_path(path)

        if primary_state == "valid":
            _atomic_write_bytes(backup, primary_raw)
        else:
            backup_state, _backup_value, _backup_raw = _read_list_state(backup)
            if primary_state == "corrupt" and backup_state != "valid":
                raise RegistryCorruptionError(
                    "Refusing to overwrite corrupt registry without a valid backup: "
                    + str(path)
                )
            if primary_state == "missing" and backup_state == "corrupt":
                raise RegistryCorruptionError(
                    "Refusing to create registry over a corrupt backup: "
                    + str(path)
                )
            if primary_state == "missing" and backup_state == "missing":
                _atomic_write_bytes(backup, payload)

        _atomic_write_bytes(path, payload)


def _append_run(event):
    try:
        with _REGISTRY_LOCK:
            os.makedirs(os.path.dirname(RUNS_FILE) or ".", exist_ok=True)
            record = dict(event)
            record["at"] = _now()
            with open(RUNS_FILE, "a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
    except OSError:
        pass


def _strings(values, maximum, length):
    if not isinstance(values, list):
        return []
    return [
        str(value).strip()[:length]
        for value in values
        if isinstance(value, str) and value.strip()
    ][:maximum]


def _expected_types(values):
    cleaned = _strings(values, 12, 24)
    if not cleaned or any(
        not value.startswith(".")
        or len(value) < 2
        or "/" in value
        or "\\" in value
        for value in cleaned
    ):
        return []
    result = []
    seen = set()
    for value in cleaned:
        normalized = value.casefold()
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _path_key(path):
    return os.path.normcase(os.path.abspath(str(path or "")))


def _identity_payload(
    capability,
    target_app,
    content_kind,
    destination_path,
    skill_scope,
    local_adapter,
    destination_kind,
    destination_id="",
    platform="",
    version_constraints=None,
):
    return {
        "schema_version": SCHEMA_VERSION,
        "capability": str(capability or "").casefold().strip(),
        "skill_scope": str(skill_scope or "").strip(),
        "target_app": str(target_app or "").casefold().strip(),
        "content_kind": str(content_kind or "").casefold().strip(),
        "local_adapter": str(local_adapter or "").strip(),
        "destination_kind": str(destination_kind or "").strip(),
        "destination_id": str(destination_id or "").strip(),
        "destination_path": _path_key(destination_path),
        "platform": str(platform or "").casefold().strip(),
        "version_constraints": sorted(
            value.casefold()
            for value in _strings(version_constraints, 8, 120)
        ),
    }


def _digest_payload(prefix, payload, length):
    material = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="ignore")
    return prefix + hashlib.sha256(material).hexdigest()[:length]


def _skill_id(
    capability,
    target_app,
    content_kind,
    destination_path,
    skill_scope="",
    local_adapter="",
    destination_kind="",
    destination_id="",
    platform="",
    version_constraints=None,
):
    payload = _identity_payload(
        capability,
        target_app,
        content_kind,
        destination_path,
        skill_scope,
        local_adapter,
        destination_kind,
        destination_id,
        platform,
        version_constraints,
    )
    return _digest_payload("skill_", payload, 20)


def _skill_id_from_record(item):
    applicability = item.get("applicability")
    if not isinstance(applicability, dict):
        applicability = {}
    return _skill_id(
        item.get("capability"),
        item.get("target_app"),
        item.get("content_kind"),
        item.get("verified_destination_path"),
        item.get("skill_scope"),
        item.get("local_adapter"),
        item.get("destination_kind"),
        item.get("destination_id"),
        applicability.get("platform"),
        applicability.get("version_constraints"),
    )


def _candidate_key(
    procedure,
    destination,
    original_request,
    session_id="",
    operation_id="",
):
    payload = _identity_payload(
        procedure.get("capability"),
        procedure.get("target_app"),
        procedure.get("content_kind"),
        destination.get("path"),
        procedure.get("skill_scope"),
        procedure.get("local_adapter"),
        destination.get("kind"),
        destination.get("id"),
        sys.platform,
        procedure.get("version_constraints"),
    )
    payload.update(
        {
            "expected_file_types": sorted(
                _expected_types(procedure.get("expected_file_types"))
            ),
            "intent_summary": str(
                procedure.get("intent_summary") or ""
            ).strip()[:400],
            "parameters": _strings(procedure.get("parameters"), 12, 100),
            "destination_hints": _strings(
                procedure.get("destination_hints"), 10, 300
            ),
            "installation_steps": _strings(
                procedure.get("installation_steps"), 14, 400
            ),
            "post_install_steps": _strings(
                procedure.get("post_install_steps"), 10, 300
            ),
            "evidence_summary": str(
                procedure.get("evidence_summary") or ""
            ).strip()[:700],
            "source_ids": _strings(procedure.get("source_ids"), 8, 80),
            "source_urls": _strings(procedure.get("source_urls"), 8, 1000),
            "destination_name": str(destination.get("name") or "").strip()[:200],
            "original_request": str(original_request or "").strip()[:900],
            "session_id": str(session_id or "").strip(),
            "operation_id": str(operation_id or "").strip(),
        }
    )
    return _digest_payload("candidate_key_", payload, 32)


def _candidate_key_from_record(item):
    applicability = item.get("applicability")
    if not isinstance(applicability, dict):
        applicability = {}
    payload = _identity_payload(
        item.get("capability"),
        item.get("target_app"),
        item.get("content_kind"),
        item.get("verified_destination_path"),
        item.get("skill_scope"),
        item.get("local_adapter"),
        item.get("destination_kind"),
        item.get("destination_id"),
        applicability.get("platform"),
        applicability.get("version_constraints"),
    )
    payload.update(
        {
            "expected_file_types": sorted(
                _expected_types(item.get("expected_file_types"))
            ),
            "intent_summary": str(item.get("intent_summary") or "").strip()[:400],
            "parameters": _strings(item.get("parameters"), 12, 100),
            "destination_hints": _strings(
                item.get("destination_hints"), 10, 300
            ),
            "installation_steps": _strings(
                item.get("installation_steps"), 14, 400
            ),
            "post_install_steps": _strings(
                item.get("post_install_steps"), 10, 300
            ),
            "evidence_summary": str(
                item.get("evidence_summary") or ""
            ).strip()[:700],
            "source_ids": _strings(item.get("source_ids"), 8, 80),
            "source_urls": _strings(item.get("source_urls"), 8, 1000),
            "destination_name": str(item.get("destination_name") or "").strip()[:200],
            "original_request": str(item.get("original_request") or "").strip()[:900],
            "session_id": str(item.get("session_id") or "").strip(),
            "operation_id": str(item.get("operation_id") or "").strip(),
        }
    )
    return _digest_payload("candidate_key_", payload, 32)


def _binding_matches(item, session_id=None, operation_id=None):
    if session_id is not None and str(item.get("session_id") or "") != str(
        session_id
    ):
        return False
    if operation_id is not None and str(item.get("operation_id") or "") != str(
        operation_id
    ):
        return False
    return True


def _parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(item):
    value = item.get("expires_at")
    if not value:
        return False
    parsed = _parse_timestamp(value)
    return parsed is not None and datetime.now(timezone.utc) >= parsed


def _action_destination_matches(candidate, action_result):
    raw_reported = action_result.get("destination")
    if not isinstance(raw_reported, str) or not raw_reported.strip():
        return False
    reported = raw_reported.strip()

    expected_name = str(candidate.get("destination_name") or "").strip()
    expected_path = str(candidate.get("verified_destination_path") or "").strip()
    name_match = bool(
        expected_name and reported.casefold() == expected_name.casefold()
    )
    path_match = bool(expected_path and _path_key(reported) == _path_key(expected_path))
    if not name_match and not path_match:
        return False

    reported_id = action_result.get("destination_id")
    if reported_id is not None and str(reported_id) != str(
        candidate.get("destination_id") or ""
    ):
        return False
    reported_kind = action_result.get("destination_kind")
    if reported_kind is not None and str(reported_kind) != str(
        candidate.get("destination_kind") or ""
    ):
        return False
    reported_path = action_result.get("destination_path")
    if reported_path is not None and _path_key(reported_path) != _path_key(
        expected_path
    ):
        return False
    return True


def _machine_result_error(candidate, action_result):
    if not isinstance(action_result, dict):
        return "Machine result is not an object."
    if action_result.get("success") is not True:
        return "Machine result did not report success."
    if action_result.get("completed") is not True:
        return "Machine result did not report completion."
    if "protected_event" in action_result:
        return "Protected events cannot be machine-verified."
    for flag in NEGATIVE_EXECUTION_FLAGS:
        if action_result.get(flag):
            return "Negative execution flag is present: " + flag

    scope = str(candidate.get("skill_scope") or "")
    action = str(action_result.get("action") or "").strip()
    if action not in ALLOWED_ACTIONS_BY_SCOPE.get(scope, set()):
        return "Execution action does not match the declared skill scope."
    if not isinstance(action_result.get("name"), str) or not action_result.get(
        "name"
    ).strip():
        return "Machine result is missing the completed object name."
    if not _action_destination_matches(candidate, action_result):
        return "Machine result destination does not match the candidate."
    return ""


def _record_error(item, expected_statuses):
    if not isinstance(item, dict):
        return "Registry record is not an object."
    if item.get("schema_version") != SCHEMA_VERSION:
        return "Unsupported or legacy schema version."
    status = str(item.get("status") or "")
    if status not in expected_statuses:
        return "Invalid lifecycle status."
    if status.startswith("pending"):
        if not str(item.get("id") or "").startswith("candidate_"):
            return "Pending record has an invalid candidate ID."
    elif status == "verified" and not str(item.get("id") or "").startswith(
        "skill_"
    ):
        return "Verified record has an invalid skill ID."

    required = (
        "capability",
        "target_app",
        "content_kind",
        "local_adapter",
        "destination_id",
        "destination_name",
        "destination_kind",
        "verified_destination_path",
    )
    for field in required:
        if not isinstance(item.get(field), str) or not item.get(field).strip():
            return "Missing required field: " + field

    scope = str(item.get("skill_scope") or "")
    if scope not in ALLOWED_SKILL_SCOPES:
        return "Invalid or missing skill scope."
    raw_expected = item.get("expected_file_types")
    normalized_expected = _expected_types(raw_expected)
    if (
        not isinstance(raw_expected, list)
        or not normalized_expected
        or raw_expected != normalized_expected
    ):
        return "Invalid or missing expected file types."

    applicability = item.get("applicability")
    if not isinstance(applicability, dict):
        return "Missing applicability object."
    for field in ("platform", "target_app", "content_kind"):
        if not isinstance(applicability.get(field), str) or not applicability.get(
            field
        ).strip():
            return "Invalid applicability field: " + field

    if item.get("expires_at") and _parse_timestamp(item.get("expires_at")) is None:
        return "Invalid candidate expiry timestamp."

    if status.startswith("pending"):
        if not str(item.get("candidate_key") or "").startswith("candidate_key_"):
            return "Missing deterministic candidate key."
        if item.get("candidate_key") != _candidate_key_from_record(item):
            return "Candidate key does not match the stored operation."

    if status == "pending_user_verification" or status == "verified":
        evidence = item.get("machine_verification")
        error = _machine_result_error(item, evidence)
        if error:
            return "Invalid machine verification: " + error

    if status == "verified":
        if item.get("id") != _skill_id_from_record(item):
            return "Verified skill ID does not match its structural identity."
        if item.get("user_verified") is not True:
            return "Verified skill has no explicit user acceptance marker."
        if not str(item.get("user_feedback") or "").strip():
            return "Verified skill has empty user acceptance evidence."
        if not str(item.get("candidate_id") or "").startswith("candidate_"):
            return "Verified skill has no originating candidate ID."
    return ""


def _quarantine_key(item, source, reason):
    return _digest_payload(
        "quarantine_",
        {"source": source, "reason": reason, "record": item},
        32,
    )


def _quarantine_records(source_path, valid, rejected, source):
    if not rejected:
        return
    invalidated = _load_list(INVALIDATED_FILE)
    existing_keys = {
        str(item.get("quarantine_key") or "")
        for item in invalidated
        if isinstance(item, dict)
    }
    archived = []
    for item, reason, status in rejected:
        key = _quarantine_key(item, source, reason)
        if key in existing_keys:
            continue
        record = dict(item) if isinstance(item, dict) else {"raw_record": item}
        record["previous_status"] = record.get("status")
        record["status"] = status
        record["invalidated_reason"] = str(reason)[:500]
        record["invalidated_at"] = _now()
        record["quarantine_key"] = key
        record["quarantine_source"] = source
        invalidated.append(record)
        existing_keys.add(key)
        archived.append(record)

    if archived:
        _save_list(INVALIDATED_FILE, invalidated, MAX_SKILLS)
    _save_list(source_path, valid, MAX_PENDING if source == "pending" else MAX_SKILLS)
    for record in archived:
        _append_run(
            {
                "event": "registry_record_quarantined",
                "source": source,
                "record_id": record.get("id"),
                "reason": record.get("invalidated_reason"),
            }
        )


def _load_valid_pending():
    with _REGISTRY_LOCK:
        raw = _load_list(PENDING_FILE)
        valid = []
        rejected = []
        for item in raw:
            error = _record_error(
                item, {"pending_execution", "pending_user_verification"}
            )
            if error:
                rejected.append((item, error, "invalid_schema"))
            elif _is_expired(item):
                rejected.append((item, "Pending candidate expired.", "expired"))
            else:
                valid.append(item)
        _quarantine_records(PENDING_FILE, valid, rejected, "pending")
        return valid


def _load_valid_skills():
    with _REGISTRY_LOCK:
        raw = _load_list(SKILLS_FILE)
        valid = []
        rejected = []
        for item in raw:
            error = _record_error(item, {"verified"})
            if error:
                rejected.append((item, error, "invalid_schema"))
            else:
                valid.append(item)
        _quarantine_records(SKILLS_FILE, valid, rejected, "verified")
        return valid


def create_pending(
    procedure,
    destination,
    original_request,
    session_id=None,
    operation_id=None,
    expires_at=None,
):
    """Save one structurally valid learned method outside verified Skills."""
    if not isinstance(procedure, dict) or not isinstance(destination, dict):
        return None
    required_procedure_text = (
        "capability",
        "skill_scope",
        "target_app",
        "content_kind",
        "local_adapter",
    )
    required_destination_text = ("id", "name", "path", "kind")
    if any(
        not isinstance(procedure.get(field), str)
        or not procedure.get(field).strip()
        for field in required_procedure_text
    ) or any(
        not isinstance(destination.get(field), str)
        or not destination.get(field).strip()
        for field in required_destination_text
    ):
        return None

    capability = str(procedure.get("capability") or "").strip()[:120]
    skill_scope = str(procedure.get("skill_scope") or "").strip()[:80]
    target_app = str(procedure.get("target_app") or "").strip()[:160]
    content_kind = str(procedure.get("content_kind") or "").strip()[:100]
    local_adapter = str(procedure.get("local_adapter") or "").strip()[:60]
    destination_id = str(destination.get("id") or "").strip()[:80]
    destination_name = str(destination.get("name") or "").strip()[:200]
    destination_kind = str(destination.get("kind") or "").strip()[:100]
    raw_path = str(destination.get("path") or "").strip()
    expected = _expected_types(procedure.get("expected_file_types"))
    if (
        not capability
        or skill_scope not in ALLOWED_SKILL_SCOPES
        or not target_app
        or not content_kind
        or not local_adapter
        or not destination_id
        or not destination_name
        or not destination_kind
        or not raw_path
        or not expected
    ):
        return None

    if expires_at is None:
        normalized_expiry = (
            datetime.now(timezone.utc) + timedelta(hours=PENDING_TTL_HOURS)
        ).isoformat()
    else:
        normalized_expiry = str(expires_at or "").strip()
        if not normalized_expiry or _parse_timestamp(normalized_expiry) is None:
            return None
    destination_path = os.path.abspath(raw_path)
    session = str(session_id or "").strip()[:160]
    operation = str(operation_id or "").strip()[:160]
    request = str(original_request or "").strip()[:900]
    intent_summary = str(procedure.get("intent_summary") or "").strip()[:400]
    evidence_summary = str(
        procedure.get("evidence_summary") or ""
    ).strip()[:700]
    now = _now()
    normalized_procedure = dict(procedure)
    normalized_procedure.update(
        {
            "capability": capability,
            "skill_scope": skill_scope,
            "target_app": target_app,
            "content_kind": content_kind,
            "local_adapter": local_adapter,
            "expected_file_types": expected,
        }
    )
    normalized_destination = dict(destination)
    normalized_destination.update(
        {
            "id": destination_id,
            "name": destination_name,
            "kind": destination_kind,
            "path": destination_path,
        }
    )
    key = _candidate_key(
        normalized_procedure,
        normalized_destination,
        request,
        session,
        operation,
    )

    with _REGISTRY_LOCK:
        items = _load_valid_pending()
        for item in items:
            if item.get("candidate_key") == key:
                _append_run(
                    {
                        "event": "skill_candidate_deduplicated",
                        "candidate_id": item.get("id"),
                        "candidate_key": key,
                    }
                )
                return item

        candidate = {
            "id": "candidate_" + uuid.uuid4().hex[:20],
            "candidate_key": key,
            "schema_version": SCHEMA_VERSION,
            "status": "pending_execution",
            "capability": capability,
            "skill_scope": skill_scope,
            "intent_summary": intent_summary,
            "target_app": target_app,
            "content_kind": content_kind,
            "applicability": {
                "platform": sys.platform,
                "target_app": target_app,
                "content_kind": content_kind,
                "version_constraints": _strings(
                    procedure.get("version_constraints"), 8, 120
                ),
            },
            "parameters": _strings(procedure.get("parameters"), 12, 100),
            "expected_file_types": expected,
            "destination_hints": _strings(
                procedure.get("destination_hints"), 10, 300
            ),
            "installation_steps": _strings(
                procedure.get("installation_steps"), 14, 400
            ),
            "post_install_steps": _strings(
                procedure.get("post_install_steps"), 10, 300
            ),
            "evidence_summary": evidence_summary,
            "source_ids": _strings(procedure.get("source_ids"), 8, 80),
            "source_urls": _strings(procedure.get("source_urls"), 8, 1000),
            "local_adapter": local_adapter,
            "destination_id": destination_id,
            "destination_name": destination_name,
            "destination_kind": destination_kind,
            "verified_destination_path": destination_path,
            "original_request": request,
            "session_id": session,
            "operation_id": operation,
            "machine_verification": None,
            "created_at": now,
            "updated_at": now,
        }
        candidate["expires_at"] = normalized_expiry
        if _record_error(candidate, {"pending_execution"}):
            return None
        items.append(candidate)
        _save_list(PENDING_FILE, items, MAX_PENDING)
        _append_run(
            {
                "event": "skill_candidate_created",
                "candidate_id": candidate["id"],
                "candidate_key": key,
            }
        )
        return candidate


def load_pending(candidate_id, session_id=None, operation_id=None):
    wanted = str(candidate_id or "").strip()
    for item in _load_valid_pending():
        if item.get("id") == wanted and _binding_matches(
            item, session_id, operation_id
        ):
            return item
    return None


def mark_execution_success(
    candidate_id,
    action_result,
    manifest=None,
    session_id=None,
    operation_id=None,
):
    """Record a scoped machine receipt; never commit a reusable skill."""
    wanted = str(candidate_id or "").strip()
    with _REGISTRY_LOCK:
        items = _load_valid_pending()
        for index, item in enumerate(items):
            if item.get("id") != wanted or not _binding_matches(
                item, session_id, operation_id
            ):
                continue
            error = _machine_result_error(item, action_result)
            if error:
                _append_run(
                    {
                        "event": "skill_candidate_machine_rejected",
                        "candidate_id": wanted,
                        "reason": error,
                    }
                )
                return None

            if item.get("status") == "pending_user_verification":
                existing = item.get("machine_verification")
                if (
                    isinstance(existing, dict)
                    and existing.get("action") == action_result.get("action")
                    and str(existing.get("destination") or "").casefold()
                    == str(action_result.get("destination") or "").casefold()
                    and str(existing.get("name") or "")
                    == str(action_result.get("name") or "")
                ):
                    return item
                return None
            if item.get("status") != "pending_execution":
                return None

            now = _now()
            updated = dict(item)
            updated["status"] = "pending_user_verification"
            updated["machine_verification"] = {
                "success": True,
                "completed": True,
                "action": str(action_result.get("action") or "")[:120],
                "name": str(action_result.get("name") or "")[:240],
                "destination": str(
                    action_result.get("destination") or ""
                )[:500],
                "destination_id": item.get("destination_id"),
                "destination_kind": item.get("destination_kind"),
                "destination_path": item.get("verified_destination_path"),
                "candidate_key": item.get("candidate_key"),
                "verified_at": now,
            }
            if isinstance(manifest, dict):
                updated["last_artifact"] = {
                    "id": str(manifest.get("id") or "")[:100],
                    "source_id": str(manifest.get("source_id") or "")[:100],
                    "name": str(manifest.get("artifact_name") or "")[:240],
                    "target_app": str(manifest.get("target_app") or "")[:160],
                    "content_kind": str(
                        manifest.get("content_kind") or ""
                    )[:100],
                    "source_url": str(manifest.get("source_url") or "")[:1000],
                }
            updated["updated_at"] = now
            if _record_error(updated, {"pending_user_verification"}):
                return None
            items[index] = updated
            _save_list(PENDING_FILE, items, MAX_PENDING)
            _append_run(
                {
                    "event": "skill_candidate_machine_verified",
                    "candidate_id": wanted,
                }
            )
            return updated
    return None


def commit_verified(
    candidate_id,
    user_feedback="",
    session_id=None,
    operation_id=None,
):
    """Commit one machine-complete candidate after explicit user acceptance."""
    wanted = str(candidate_id or "").strip()
    if not isinstance(user_feedback, str):
        return None
    feedback = user_feedback.strip()[:400]
    if not wanted or not feedback:
        return None

    with _REGISTRY_LOCK:
        skills = _load_valid_skills()
        already_committed = next(
            (
                item
                for item in skills
                if item.get("candidate_id") == wanted
                and item.get("status") == "verified"
                and _binding_matches(item, session_id, operation_id)
            ),
            None,
        )
        pending = _load_valid_pending()
        candidate_index = next(
            (
                index
                for index, item in enumerate(pending)
                if item.get("id") == wanted
                and _binding_matches(item, session_id, operation_id)
            ),
            None,
        )

        if already_committed:
            if candidate_index is not None:
                del pending[candidate_index]
                _save_list(PENDING_FILE, pending, MAX_PENDING)
                _append_run(
                    {
                        "event": "skill_commit_reconciled",
                        "candidate_id": wanted,
                        "skill_id": already_committed.get("id"),
                    }
                )
            return already_committed

        if candidate_index is None:
            return None
        item = pending[candidate_index]
        if item.get("status") != "pending_user_verification":
            return None
        evidence_error = _machine_result_error(
            item, item.get("machine_verification")
        )
        if evidence_error:
            return None

        now = _now()
        skill = dict(item)
        skill["id"] = _skill_id_from_record(item)
        skill["status"] = "verified"
        skill["candidate_id"] = wanted
        skill["user_verified"] = True
        skill["user_feedback"] = feedback
        skill["user_acceptance"] = {
            "accepted": True,
            "feedback": feedback,
            "accepted_at": now,
            "session_id": str(item.get("session_id") or ""),
            "operation_id": str(item.get("operation_id") or ""),
        }
        skill["verified_at"] = now
        skill["last_verified_at"] = now
        skill["success_count"] = 1
        skill["failure_count"] = 0
        skill["updated_at"] = now
        skill.pop("original_request", None)
        skill.pop("expires_at", None)

        for skill_index, existing in enumerate(skills):
            if existing.get("id") == skill["id"]:
                skill["created_at"] = existing.get("created_at", now)
                try:
                    previous_successes = int(existing.get("success_count", 0))
                except (TypeError, ValueError):
                    previous_successes = 0
                try:
                    previous_failures = int(existing.get("failure_count", 0))
                except (TypeError, ValueError):
                    previous_failures = 0
                skill["success_count"] = max(0, previous_successes) + 1
                skill["failure_count"] = max(0, previous_failures)
                skills[skill_index] = skill
                break
        else:
            skill["created_at"] = now
            skills.append(skill)

        if _record_error(skill, {"verified"}):
            return None
        _save_list(SKILLS_FILE, skills, MAX_SKILLS)
        del pending[candidate_index]
        _save_list(PENDING_FILE, pending, MAX_PENDING)
        _append_run(
            {
                "event": "skill_committed",
                "candidate_id": wanted,
                "skill_id": skill["id"],
            }
        )
        return skill


def discard_pending(
    candidate_id,
    reason,
    user_rejected=False,
    session_id=None,
    operation_id=None,
):
    wanted = str(candidate_id or "").strip()
    with _REGISTRY_LOCK:
        pending = _load_valid_pending()
        for index, item in enumerate(pending):
            if item.get("id") != wanted or not _binding_matches(
                item, session_id, operation_id
            ):
                continue
            removed = dict(item)
            removed["previous_status"] = removed.get("status")
            removed["status"] = "user_rejected" if user_rejected else "failed"
            removed["invalidated_reason"] = str(reason or "")[:500]
            removed["invalidated_at"] = _now()
            removed["quarantine_source"] = "pending"
            removed["quarantine_key"] = _quarantine_key(
                item, "pending", removed["invalidated_reason"]
            )
            invalidated = _load_list(INVALIDATED_FILE)
            if not any(
                isinstance(existing, dict)
                and existing.get("quarantine_key") == removed["quarantine_key"]
                for existing in invalidated
            ):
                invalidated.append(removed)
                _save_list(INVALIDATED_FILE, invalidated, MAX_SKILLS)
            del pending[index]
            _save_list(PENDING_FILE, pending, MAX_PENDING)
            _append_run(
                {
                    "event": "skill_candidate_discarded",
                    "candidate_id": wanted,
                    "user_rejected": bool(user_rejected),
                }
            )
            return True

        return any(
            isinstance(item, dict)
            and item.get("id") == wanted
            and _binding_matches(item, session_id, operation_id)
            for item in _load_list(INVALIDATED_FILE)
        )


def load_verified(skill_id):
    wanted = str(skill_id or "").strip()
    for item in _load_valid_skills():
        if item.get("id") == wanted:
            return item
    return None


def forget_verified(skill_id, confirmed=False):
    """Remove one exact verified skill only after explicit user confirmation.

    This is the authoritative destructive boundary for learned skills.  The
    caller must resolve an existing opaque skill ID first and must pass the
    literal boolean ``True`` after a separate confirmation turn.
    """
    wanted = str(skill_id or "").strip()
    if confirmed is not True or not wanted.startswith("skill_"):
        return None

    with _REGISTRY_LOCK:
        skills = _load_valid_skills()
        removed = next(
            (
                dict(item)
                for item in skills
                if isinstance(item, dict) and item.get("id") == wanted
            ),
            None,
        )
        if removed is None:
            return None

        remaining = [
            item
            for item in skills
            if not isinstance(item, dict) or item.get("id") != wanted
        ]
        _save_list(SKILLS_FILE, remaining, MAX_SKILLS)

        # A user-forgotten skill must not be resurrected from the normal
        # one-generation recovery backup if the primary file is later damaged.
        payload = (
            json.dumps(remaining[-MAX_SKILLS:], ensure_ascii=False, indent=2)
            + "\n"
        ).encode("utf-8")
        _atomic_write_bytes(_backup_path(SKILLS_FILE), payload)
        _append_run({"event": "verified_skill_forgotten", "skill_id": wanted})
        return removed


def _skill_summaries():
    summaries = []
    for item in _load_valid_skills()[-MAX_SKILLS:]:
        summaries.append(
            {
                "id": item.get("id"),
                "capability": item.get("capability"),
                "skill_scope": item.get("skill_scope"),
                "intent_summary": item.get("intent_summary"),
                "target_app": item.get("target_app"),
                "content_kind": item.get("content_kind"),
                "local_adapter": item.get("local_adapter"),
                "destination_kind": item.get("destination_kind"),
                "expected_file_types": item.get("expected_file_types"),
                "applicability": item.get("applicability"),
                "parameters": item.get("parameters"),
                "last_verified_at": item.get("last_verified_at"),
            }
        )
    return summaries


def match_verified(message, recent_context=""):
    """Let AI choose one exact verified skill ID; Python does no intent matching."""
    summaries = _skill_summaries()
    if not summaries:
        return None
    import tools

    payload = {
        "request": str(message)[:900],
        "recent_context": str(recent_context)[-700:],
        "verified_skills": summaries,
    }
    result = tools.run_ai_prompt(
        "prompts/casper_skill_match.txt",
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        expect_json=True,
        num_ctx=4096,
        num_predict=500,
        think=False,
        model_name="gemma4:12b",
    )
    if not isinstance(result, dict) or str(result.get("decision", "")).upper() != "USE":
        return None
    selected_id = str(result.get("skill_id") or "")
    valid_ids = {str(item.get("id")) for item in summaries}
    return load_verified(selected_id) if selected_id in valid_ids else None


def _pending_resume_summaries(session_id=None, operation_id=None):
    summaries = []
    for item in _load_valid_pending()[-MAX_PENDING:]:
        if item.get("status") != "pending_execution" or not _binding_matches(
            item, session_id, operation_id
        ):
            continue
        summaries.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "capability": item.get("capability"),
                "skill_scope": item.get("skill_scope"),
                "intent_summary": item.get("intent_summary"),
                "target_app": item.get("target_app"),
                "content_kind": item.get("content_kind"),
                "version_constraints": (
                    item.get("applicability", {}).get("version_constraints", [])
                    if isinstance(item.get("applicability"), dict)
                    else []
                ),
                "expected_file_types": item.get("expected_file_types"),
                "local_adapter": item.get("local_adapter"),
                "destination_kind": item.get("destination_kind"),
                "destination_name": item.get("destination_name"),
                "original_request": item.get("original_request"),
                "operation_id": item.get("operation_id"),
                "updated_at": item.get("updated_at"),
            }
        )
    return summaries


def match_pending_resume(
    message,
    recent_context="",
    session_id=None,
    operation_id=None,
):
    """Let AI restore one valid pending candidate after a checkpoint expired."""
    summaries = _pending_resume_summaries(session_id, operation_id)
    if not summaries:
        return None
    import tools

    payload = {
        "current_message": str(message)[:600],
        "recent_context": str(recent_context)[-2200:],
        "pending_candidates": summaries,
    }
    valid_ids = {str(item.get("id")) for item in summaries}
    for output_budget in (1800, 3000):
        result = tools.run_ai_prompt(
            "prompts/casper_pending_skill_resume.txt",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            expect_json=True,
            num_ctx=8192,
            num_predict=output_budget,
            think=False,
            model_name="gemma4:12b",
        )
        if not isinstance(result, dict):
            payload["retry_instruction"] = (
                "Return only the compact resume decision JSON now."
            )
            continue
        decision = str(result.get("decision") or "").upper()
        if decision == "NONE":
            return None
        if decision == "CLARIFY":
            return {"decision": "CLARIFY"}
        selected_id = str(result.get("candidate_id") or "")
        resume_request = str(result.get("resume_request") or "").strip()
        if decision == "RESUME" and selected_id in valid_ids and resume_request:
            skill = load_pending(
                selected_id,
                session_id=session_id,
                operation_id=operation_id,
            )
            if skill:
                return {
                    "skill": skill,
                    "resume_request": resume_request[:900],
                }
        payload["retry_instruction"] = (
            "Use one exact candidate ID and a substantive request, or NONE."
        )
    return None


def classify_user_verification(message, pending_action, recent_context=""):
    """AI decides whether user feedback accepts or rejects the pending skill."""
    import tools

    payload = {
        "user_message": str(message)[:600],
        "pending_action": pending_action,
        "recent_context": str(recent_context)[-800:],
    }
    input_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    allowed = {"ACCEPT", "REJECT", "CLARIFY", "UNRELATED"}
    attempts = (
        (
            "prompts/casper_skill_user_verification.txt",
            "gemma4:12b",
            4096,
            900,
        ),
        (
            "prompts/casper_skill_user_verification_retry.txt",
            "gemma4:e4b",
            4096,
            1200,
        ),
    )
    for prompt_path, model_name, context_budget, output_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in allowed:
            return value
    return "CLARIFY"


def classify_learning_checkpoint(message, pending_action, recent_context=""):
    """Let AI interpret the reply to a learn-then-continue checkpoint."""
    import tools

    payload = {
        "user_message": str(message)[:600],
        "pending_action": pending_action,
        "recent_context": str(recent_context)[-800:],
    }
    input_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    allowed = {"CONTINUE", "REJECT", "CLARIFY", "UNRELATED"}
    attempts = (
        (
            "prompts/casper_skill_learning_checkpoint.txt",
            "llama3.2:latest",
            4096,
            512,
        ),
        (
            "prompts/casper_skill_learning_checkpoint_retry.txt",
            "gemma4:12b",
            8192,
            2400,
        ),
    )
    for prompt_path, model_name, context_budget, output_budget in attempts:
        raw = tools.run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=False,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        value = str(raw or "").strip().upper()
        if value in allowed:
            return value
    return "CLARIFY"


def resolve_resume_request(message, pending_action, recent_context=""):
    """Let AI recover the substantive request behind a continuation reply."""
    import tools

    payload = {
        "current_reply": str(message)[:400],
        "pending_action": pending_action,
        "recent_context": str(recent_context)[-1800:],
    }
    input_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    attempts = (
        (
            "prompts/casper_skill_resume_request.txt",
            "llama3.2:latest",
            8192,
            1400,
        ),
        (
            "prompts/casper_skill_resume_request_retry.txt",
            "gemma4:12b",
            8192,
            3600,
        ),
    )
    for prompt_path, model_name, context_budget, output_budget in attempts:
        result = tools.run_ai_prompt(
            prompt_path,
            input_text,
            expect_json=True,
            num_ctx=context_budget,
            num_predict=output_budget,
            think=False,
            model_name=model_name,
        )
        if not isinstance(result, dict) or result.get("found") is not True:
            continue
        request = str(result.get("resume_request") or "").strip()
        if request:
            return request[:900]
    return ""


def record_verified_reuse(skill_id):
    wanted = str(skill_id or "").strip()
    with _REGISTRY_LOCK:
        skills = _load_valid_skills()
        for index, item in enumerate(skills):
            if item.get("id") != wanted:
                continue
            updated = dict(item)
            try:
                successes = int(item.get("success_count", 0))
            except (TypeError, ValueError):
                successes = 0
            updated["success_count"] = max(0, successes) + 1
            updated["last_used_at"] = _now()
            updated["updated_at"] = updated["last_used_at"]
            skills[index] = updated
            _save_list(SKILLS_FILE, skills, MAX_SKILLS)
            _append_run({"event": "verified_skill_reused", "skill_id": wanted})
            return updated
    return None
