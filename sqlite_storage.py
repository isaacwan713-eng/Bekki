"""Transactional SQLite storage with lossless JSON/JSONL compatibility.

JSON documents and append-only JSONL streams are imported on first access.
SQLite then becomes authoritative while the legacy files remain readable
rollback mirrors.  The module deliberately depends only on Python's standard
library so a storage failure can always fail open to the legacy files.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DATABASE_FILENAME = "bekki.sqlite3"
SCHEMA_VERSION = 2
MIGRATION_BACKUP_SUFFIX = ".pre-sqlite-v1.bak"
PHASE_TWO_MIGRATION_BACKUP_SUFFIX = ".pre-sqlite-v2.bak"
BUSY_TIMEOUT_MILLISECONDS = 10_000

_MISSING = object()
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _canonical_payload(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_digest(value):
    return hashlib.sha256(_canonical_payload(value).encode("utf-8")).hexdigest()


def _data_directory_for(legacy_path):
    path = Path(legacy_path).resolve()
    for parent in path.parents:
        if parent.name.casefold() == "data":
            return parent
    # Tests and embedders may redirect DATA_DIR to a temporary directory whose
    # name is not literally "data".  These established nested store names
    # still identify their shared root without requiring a second database.
    for parent in path.parents:
        if parent.name.casefold() in {"contexts", "knowledge", "nerv"}:
            return parent.parent
    # Preserve the phase-one test/runtime convention for a standalone
    # contexts directory even when its parent is not literally named data.
    if path.parent.name.casefold() == "contexts":
        return path.parent.parent
    return path.parent


def database_path_for(legacy_path):
    """Return the one SQLite database belonging to the nearest data root."""

    return _data_directory_for(legacy_path) / DATABASE_FILENAME


def document_key_for(legacy_path):
    """Return a stable nested key for a compatibility mirror path."""

    path = Path(legacy_path).resolve()
    data_directory = _data_directory_for(path)
    try:
        return path.relative_to(data_directory).as_posix()
    except ValueError:
        pass
    return path.name


def _thread_lock(database_path):
    key = str(Path(database_path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _process_lock(database_path):
    """Serialize the SQLite commit and compatibility mirror across processes."""

    lock_path = Path(str(database_path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _connect(database_path):
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        str(path),
        timeout=BUSY_TIMEOUT_MILLISECONDS / 1000,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA busy_timeout = " + str(BUSY_TIMEOUT_MILLISECONDS)
    )
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute("PRAGMA foreign_keys = ON")
    _ensure_schema(connection)
    return connection


def _ensure_schema(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS storage_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS json_documents (
            namespace TEXT NOT NULL,
            document_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, document_key)
        );

        CREATE TABLE IF NOT EXISTS json_migrations (
            namespace TEXT NOT NULL,
            document_key TEXT NOT NULL,
            source_path TEXT,
            backup_path TEXT,
            source_sha256 TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, document_key)
        );

        CREATE TABLE IF NOT EXISTS jsonl_streams (
            namespace TEXT NOT NULL,
            stream_key TEXT NOT NULL,
            event_count INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, stream_key)
        );

        CREATE TABLE IF NOT EXISTS jsonl_events (
            namespace TEXT NOT NULL,
            stream_key TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            payload TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (namespace, stream_key, sequence),
            FOREIGN KEY (namespace, stream_key)
                REFERENCES jsonl_streams(namespace, stream_key)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS jsonl_migrations (
            namespace TEXT NOT NULL,
            stream_key TEXT NOT NULL,
            source_path TEXT,
            backup_path TEXT,
            source_sha256 TEXT NOT NULL,
            valid_line_count INTEGER NOT NULL,
            rejected_line_count INTEGER NOT NULL,
            migrated_at TEXT NOT NULL,
            PRIMARY KEY (namespace, stream_key)
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO storage_metadata(key, value) VALUES(?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    connection.execute("PRAGMA user_version = " + str(SCHEMA_VERSION))


def _validate_identity(namespace, document_key):
    namespace = str(namespace or "").strip()
    document_key = str(document_key or "").strip()
    if not namespace or not document_key:
        raise ValueError("SQLite storage identity cannot be empty")
    return namespace[:120], document_key[:240]


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return _MISSING


def _read_legacy(path):
    primary = _read_json(path)
    if primary is not _MISSING:
        return primary, Path(path)
    backup_path = Path(str(path) + ".bak")
    backup = _read_json(backup_path)
    if backup is not _MISSING:
        return backup, backup_path
    return _MISSING, None


def _fsync_directory(directory):
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = None
    try:
        descriptor = os.open(str(directory), os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _temporary_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return temporary


def _write_json_mirror(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    primary_temporary = _temporary_json(path, value)
    backup_temporary = None
    try:
        previous = _read_json(path)
        if previous is not _MISSING:
            backup_path = Path(str(path) + ".bak")
            backup_temporary = _temporary_json(backup_path, previous)
            os.replace(backup_temporary, backup_path)
            backup_temporary = None
        os.replace(primary_temporary, path)
        primary_temporary = None
        _fsync_directory(path.parent)
    finally:
        for temporary in (primary_temporary, backup_temporary):
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def _migration_backup(
    source_path,
    legacy_path,
    suffix=MIGRATION_BACKUP_SUFFIX,
):
    if source_path is None:
        return None
    legacy_path = Path(legacy_path)
    backup_path = Path(str(legacy_path) + str(suffix))
    if backup_path.exists():
        return backup_path
    try:
        shutil.copy2(source_path, backup_path)
        return backup_path
    except OSError as error:
        print("[SQLITE STORAGE] migration backup failed:", repr(error))
        return None


def _row_value(row):
    if row is None:
        return _MISSING
    try:
        return json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError, ValueError):
        return _MISSING


def _legacy_is_newer(path, sqlite_updated_at):
    try:
        updated_at = datetime.fromisoformat(str(sqlite_updated_at or ""))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return Path(path).stat().st_mtime_ns > int(
            updated_at.timestamp() * 1_000_000_000
        )
    except (OSError, TypeError, ValueError, OverflowError):
        return False


def _upsert_document(connection, namespace, document_key, value):
    payload = _canonical_payload(value)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    connection.execute(
        """
        INSERT INTO json_documents(
            namespace, document_key, payload, payload_sha256, updated_at
        ) VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(namespace, document_key) DO UPDATE SET
            payload = excluded.payload,
            payload_sha256 = excluded.payload_sha256,
            updated_at = excluded.updated_at
        """,
        (namespace, document_key, payload, digest, _now_iso()),
    )
    return digest


def _record_migration(
    connection,
    namespace,
    document_key,
    source_path,
    backup_path,
    source_digest,
):
    connection.execute(
        """
        INSERT OR IGNORE INTO json_migrations(
            namespace, document_key, source_path, backup_path,
            source_sha256, migrated_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            namespace,
            document_key,
            str(source_path) if source_path is not None else None,
            str(backup_path) if backup_path is not None else None,
            source_digest,
            _now_iso(),
        ),
    )


def _fallback_value(legacy_path, default):
    value, _source = _read_legacy(legacy_path)
    return default if value is _MISSING else value


def load_document(
    namespace,
    document_key,
    legacy_path,
    default,
    migration_backup_suffix=MIGRATION_BACKUP_SUFFIX,
):
    """Load one document, importing or reconciling its JSON mirror safely."""

    namespace, document_key = _validate_identity(namespace, document_key)
    legacy_path = Path(legacy_path).resolve()
    database_path = database_path_for(legacy_path)
    lock = _thread_lock(database_path)

    with lock:
        try:
            with _process_lock(database_path):
                connection = _connect(database_path)
                try:
                    row = connection.execute(
                        """
                        SELECT payload, payload_sha256, updated_at
                        FROM json_documents
                        WHERE namespace = ? AND document_key = ?
                        """,
                        (namespace, document_key),
                    ).fetchone()
                    stored_value = _row_value(row)
                    legacy_value, source_path = _read_legacy(legacy_path)

                    if stored_value is not _MISSING:
                        if legacy_value is not _MISSING and source_path == legacy_path:
                            legacy_digest = _payload_digest(legacy_value)
                            if (
                                legacy_digest != row["payload_sha256"]
                                and _legacy_is_newer(
                                    legacy_path,
                                    row["updated_at"],
                                )
                            ):
                                connection.execute("BEGIN IMMEDIATE")
                                try:
                                    _upsert_document(
                                        connection,
                                        namespace,
                                        document_key,
                                        legacy_value,
                                    )
                                    connection.execute("COMMIT")
                                except Exception:
                                    connection.execute("ROLLBACK")
                                    raise
                                print(
                                    "[SQLITE STORAGE] imported newer JSON mirror:",
                                    namespace + "/" + document_key,
                                )
                                return legacy_value

                            if legacy_digest != row["payload_sha256"]:
                                _write_json_mirror(legacy_path, stored_value)
                                return stored_value

                        if legacy_value is _MISSING or source_path != legacy_path:
                            _write_json_mirror(legacy_path, stored_value)
                        return stored_value

                    initial_value = (
                        default if legacy_value is _MISSING else legacy_value
                    )
                    backup_path = _migration_backup(
                        source_path,
                        legacy_path,
                        migration_backup_suffix,
                    )
                    source_digest = _payload_digest(initial_value)
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        _upsert_document(
                            connection,
                            namespace,
                            document_key,
                            initial_value,
                        )
                        _record_migration(
                            connection,
                            namespace,
                            document_key,
                            source_path,
                            backup_path,
                            source_digest,
                        )
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise

                    if legacy_value is _MISSING or source_path != legacy_path:
                        _write_json_mirror(legacy_path, initial_value)
                    print(
                        "[SQLITE STORAGE] migrated:",
                        namespace + "/" + document_key,
                    )
                    return initial_value
                finally:
                    connection.close()
        except (OSError, sqlite3.Error) as error:
            print("[SQLITE STORAGE] load fallback:", repr(error))
            return _fallback_value(legacy_path, default)


def save_document(
    namespace,
    document_key,
    legacy_path,
    value,
    migration_backup_suffix=MIGRATION_BACKUP_SUFFIX,
):
    """Commit to SQLite and refresh the rollback-compatible JSON mirror."""

    namespace, document_key = _validate_identity(namespace, document_key)
    legacy_path = Path(legacy_path).resolve()
    database_path = database_path_for(legacy_path)
    lock = _thread_lock(database_path)

    with lock:
        with _process_lock(database_path):
            sqlite_saved = False
            connection = None
            try:
                connection = _connect(database_path)
                existing = connection.execute(
                    """
                    SELECT 1 FROM json_documents
                    WHERE namespace = ? AND document_key = ?
                    """,
                    (namespace, document_key),
                ).fetchone()
                source_value, source_path = _read_legacy(legacy_path)
                backup_path = None
                if existing is None:
                    backup_path = _migration_backup(
                        source_path,
                        legacy_path,
                        migration_backup_suffix,
                    )

                connection.execute("BEGIN IMMEDIATE")
                try:
                    digest = _upsert_document(
                        connection,
                        namespace,
                        document_key,
                        value,
                    )
                    if existing is None:
                        migration_digest = (
                            _payload_digest(source_value)
                            if source_value is not _MISSING
                            else digest
                        )
                        _record_migration(
                            connection,
                            namespace,
                            document_key,
                            source_path,
                            backup_path,
                            migration_digest,
                        )
                    connection.execute("COMMIT")
                    sqlite_saved = True
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
            except (OSError, sqlite3.Error) as error:
                print("[SQLITE STORAGE] save fallback:", repr(error))
            finally:
                if connection is not None:
                    connection.close()

            _write_json_mirror(legacy_path, value)
            return sqlite_saved


def _read_jsonl(path):
    """Return canonical valid lines, rejected-line count and exact bytes."""

    try:
        raw = Path(path).read_bytes()
    except (FileNotFoundError, OSError):
        return [], 0, False, b""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    payloads = []
    rejected = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payloads.append(_canonical_payload(json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            rejected += 1
    return payloads, rejected, True, raw


def _stream_digest(payloads):
    """Hash an ordered stream without depending on JSONL whitespace."""

    digest = hashlib.sha256(b"").hexdigest()
    for payload in payloads:
        digest = hashlib.sha256(
            (digest + "\n" + payload).encode("utf-8")
        ).hexdigest()
    return digest


def _jsonl_text(payloads):
    lines = [
        json.dumps(json.loads(payload), ensure_ascii=False)
        for payload in payloads
    ]
    return "" if not lines else "\n".join(lines) + "\n"


def _temporary_bytes(path, content):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix="." + path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return temporary


def _write_jsonl_mirror(path, payloads):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    primary_temporary = _temporary_bytes(
        path,
        _jsonl_text(payloads).encode("utf-8"),
    )
    backup_temporary = None
    try:
        try:
            previous = path.read_bytes()
        except (FileNotFoundError, OSError):
            previous = None
        if previous is not None:
            backup_path = Path(str(path) + ".bak")
            backup_temporary = _temporary_bytes(backup_path, previous)
            os.replace(backup_temporary, backup_path)
            backup_temporary = None
        os.replace(primary_temporary, path)
        primary_temporary = None
        _fsync_directory(path.parent)
    finally:
        for temporary in (primary_temporary, backup_temporary):
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def _append_jsonl_mirror(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(json.loads(payload), ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _stream_payloads(connection, namespace, stream_key):
    return [
        row["payload"]
        for row in connection.execute(
            """
            SELECT payload FROM jsonl_events
            WHERE namespace = ? AND stream_key = ?
            ORDER BY sequence
            """,
            (namespace, stream_key),
        )
    ]


def _replace_stream(connection, namespace, stream_key, payloads):
    timestamp = _now_iso()
    connection.execute(
        """
        INSERT INTO jsonl_streams(
            namespace, stream_key, event_count, content_sha256, updated_at
        ) VALUES(?, ?, 0, ?, ?)
        ON CONFLICT(namespace, stream_key) DO UPDATE SET
            event_count = 0,
            content_sha256 = excluded.content_sha256,
            updated_at = excluded.updated_at
        """,
        (namespace, stream_key, _stream_digest([]), timestamp),
    )
    connection.execute(
        "DELETE FROM jsonl_events WHERE namespace = ? AND stream_key = ?",
        (namespace, stream_key),
    )
    for sequence, payload in enumerate(payloads, start=1):
        connection.execute(
            """
            INSERT INTO jsonl_events(
                namespace, stream_key, sequence, payload,
                payload_sha256, recorded_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                namespace,
                stream_key,
                sequence,
                payload,
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                timestamp,
            ),
        )
    connection.execute(
        """
        UPDATE jsonl_streams
        SET event_count = ?, content_sha256 = ?, updated_at = ?
        WHERE namespace = ? AND stream_key = ?
        """,
        (
            len(payloads),
            _stream_digest(payloads),
            timestamp,
            namespace,
            stream_key,
        ),
    )


def _append_stream_payloads(connection, namespace, stream_key, payloads):
    if not payloads:
        return
    row = connection.execute(
        """
        SELECT event_count, content_sha256 FROM jsonl_streams
        WHERE namespace = ? AND stream_key = ?
        """,
        (namespace, stream_key),
    ).fetchone()
    if row is None:
        _replace_stream(connection, namespace, stream_key, [])
        row = connection.execute(
            """
            SELECT event_count, content_sha256 FROM jsonl_streams
            WHERE namespace = ? AND stream_key = ?
            """,
            (namespace, stream_key),
        ).fetchone()
    sequence = int(row["event_count"])
    digest = str(row["content_sha256"])
    timestamp = _now_iso()
    for payload in payloads:
        sequence += 1
        digest = hashlib.sha256(
            (digest + "\n" + payload).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO jsonl_events(
                namespace, stream_key, sequence, payload,
                payload_sha256, recorded_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                namespace,
                stream_key,
                sequence,
                payload,
                hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                timestamp,
            ),
        )
    connection.execute(
        """
        UPDATE jsonl_streams
        SET event_count = ?, content_sha256 = ?, updated_at = ?
        WHERE namespace = ? AND stream_key = ?
        """,
        (sequence, digest, timestamp, namespace, stream_key),
    )


def _record_jsonl_migration(
    connection,
    namespace,
    stream_key,
    source_path,
    backup_path,
    raw_source,
    valid_line_count,
    rejected_line_count,
):
    connection.execute(
        """
        INSERT OR IGNORE INTO jsonl_migrations(
            namespace, stream_key, source_path, backup_path,
            source_sha256, valid_line_count, rejected_line_count, migrated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            namespace,
            stream_key,
            str(source_path) if source_path is not None else None,
            str(backup_path) if backup_path is not None else None,
            hashlib.sha256(raw_source).hexdigest(),
            int(valid_line_count),
            int(rejected_line_count),
            _now_iso(),
        ),
    )


def _external_stream_tail(stored_payloads, mirror_payloads):
    common = 0
    maximum = min(len(stored_payloads), len(mirror_payloads))
    while (
        common < maximum
        and stored_payloads[common] == mirror_payloads[common]
    ):
        common += 1
    if common == len(mirror_payloads):
        return []
    return mirror_payloads[common:]


def _stream_matches(row, payloads, rejected):
    return bool(
        row is not None
        and rejected == 0
        and int(row["event_count"]) == len(payloads)
        and str(row["content_sha256"]) == _stream_digest(payloads)
    )


def _reconcile_stream(
    connection,
    namespace,
    stream_key,
    legacy_path,
    row,
    mirror_payloads,
    rejected,
    mirror_exists,
):
    """Import only external append history; never discard committed events."""

    if mirror_exists and _stream_matches(row, mirror_payloads, rejected):
        return False
    imported = []
    if mirror_exists and _legacy_is_newer(legacy_path, row["updated_at"]):
        stored_payloads = _stream_payloads(
            connection,
            namespace,
            stream_key,
        )
        imported = _external_stream_tail(stored_payloads, mirror_payloads)
        _append_stream_payloads(
            connection,
            namespace,
            stream_key,
            imported,
        )
        if imported:
            print(
                "[SQLITE STORAGE] imported newer JSONL mirror:",
                namespace + "/" + stream_key,
                "events=" + str(len(imported)),
            )
    return True


def append_event(
    namespace,
    stream_key,
    legacy_path,
    event,
    migration_backup_suffix=PHASE_TWO_MIGRATION_BACKUP_SUFFIX,
):
    """Append one event transactionally and refresh its JSONL mirror."""

    namespace, stream_key = _validate_identity(namespace, stream_key)
    legacy_path = Path(legacy_path).resolve()
    database_path = database_path_for(legacy_path)
    payload = _canonical_payload(event)
    lock = _thread_lock(database_path)

    with lock:
        try:
            with _process_lock(database_path):
                connection = _connect(database_path)
                rewrite_mirror = False
                final_payloads = None
                try:
                    row = connection.execute(
                        """
                        SELECT event_count, content_sha256, updated_at
                        FROM jsonl_streams
                        WHERE namespace = ? AND stream_key = ?
                        """,
                        (namespace, stream_key),
                    ).fetchone()
                    (
                        mirror_payloads,
                        rejected,
                        mirror_exists,
                        raw_source,
                    ) = _read_jsonl(legacy_path)
                    source_path = legacy_path if mirror_exists else None
                    backup_path = None
                    if row is None:
                        backup_path = _migration_backup(
                            source_path,
                            legacy_path,
                            migration_backup_suffix,
                        )

                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        if row is None:
                            _replace_stream(
                                connection,
                                namespace,
                                stream_key,
                                mirror_payloads,
                            )
                            _record_jsonl_migration(
                                connection,
                                namespace,
                                stream_key,
                                source_path,
                                backup_path,
                                raw_source,
                                len(mirror_payloads),
                                rejected,
                            )
                            rewrite_mirror = (
                                not mirror_exists
                                or rejected > 0
                                or bool(raw_source and not raw_source.endswith(b"\n"))
                            )
                        else:
                            rewrite_mirror = _reconcile_stream(
                                connection,
                                namespace,
                                stream_key,
                                legacy_path,
                                row,
                                mirror_payloads,
                                rejected,
                                mirror_exists,
                            )
                            if raw_source and not raw_source.endswith(b"\n"):
                                rewrite_mirror = True
                        _append_stream_payloads(
                            connection,
                            namespace,
                            stream_key,
                            [payload],
                        )
                        if rewrite_mirror:
                            final_payloads = _stream_payloads(
                                connection,
                                namespace,
                                stream_key,
                            )
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
                finally:
                    connection.close()

                try:
                    if rewrite_mirror:
                        _write_jsonl_mirror(legacy_path, final_payloads or [])
                    else:
                        _append_jsonl_mirror(legacy_path, payload)
                except OSError as error:
                    # SQLite already committed.  The next access reconstructs
                    # the mirror, so never append a duplicate through fallback.
                    print("[SQLITE STORAGE] JSONL mirror pending:", repr(error))
                return True
        except (OSError, sqlite3.Error) as error:
            print("[SQLITE STORAGE] event fallback:", repr(error))
            _append_jsonl_mirror(legacy_path, payload)
            return False


def load_event_stream(
    namespace,
    stream_key,
    legacy_path,
    migration_backup_suffix=PHASE_TWO_MIGRATION_BACKUP_SUFFIX,
):
    """Load and reconcile a JSONL stream for diagnostics and recovery."""

    namespace, stream_key = _validate_identity(namespace, stream_key)
    legacy_path = Path(legacy_path).resolve()
    database_path = database_path_for(legacy_path)
    lock = _thread_lock(database_path)

    with lock:
        try:
            with _process_lock(database_path):
                connection = _connect(database_path)
                try:
                    row = connection.execute(
                        """
                        SELECT event_count, content_sha256, updated_at
                        FROM jsonl_streams
                        WHERE namespace = ? AND stream_key = ?
                        """,
                        (namespace, stream_key),
                    ).fetchone()
                    payloads, rejected, exists, raw_source = _read_jsonl(
                        legacy_path
                    )
                    rewrite_mirror = False
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        if row is None:
                            source_path = legacy_path if exists else None
                            backup_path = _migration_backup(
                                source_path,
                                legacy_path,
                                migration_backup_suffix,
                            )
                            _replace_stream(
                                connection,
                                namespace,
                                stream_key,
                                payloads,
                            )
                            _record_jsonl_migration(
                                connection,
                                namespace,
                                stream_key,
                                source_path,
                                backup_path,
                                raw_source,
                                len(payloads),
                                rejected,
                            )
                            rewrite_mirror = not exists or rejected > 0
                        else:
                            rewrite_mirror = _reconcile_stream(
                                connection,
                                namespace,
                                stream_key,
                                legacy_path,
                                row,
                                payloads,
                                rejected,
                                exists,
                            )
                        final_payloads = _stream_payloads(
                            connection,
                            namespace,
                            stream_key,
                        )
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
                finally:
                    connection.close()
                if rewrite_mirror:
                    _write_jsonl_mirror(legacy_path, final_payloads)
                return [json.loads(payload) for payload in final_payloads]
        except (OSError, sqlite3.Error) as error:
            print("[SQLITE STORAGE] stream fallback:", repr(error))
            payloads, _rejected, _exists, _raw = _read_jsonl(legacy_path)
            return [json.loads(payload) for payload in payloads]


def delete_document(
    namespace,
    document_key,
    legacy_path,
    delete_legacy=True,
):
    namespace, document_key = _validate_identity(namespace, document_key)
    legacy_path = Path(legacy_path).resolve()
    database_path = database_path_for(legacy_path)
    lock = _thread_lock(database_path)

    with lock:
        with _process_lock(database_path):
            try:
                connection = _connect(database_path)
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """
                        DELETE FROM json_documents
                        WHERE namespace = ? AND document_key = ?
                        """,
                        (namespace, document_key),
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as error:
                print("[SQLITE STORAGE] delete fallback:", repr(error))

            if delete_legacy:
                for candidate in (legacy_path, Path(str(legacy_path) + ".bak")):
                    try:
                        candidate.unlink()
                    except FileNotFoundError:
                        pass


def document_exists(namespace, document_key, legacy_path):
    """Check for a SQLite row or readable primary JSON without migrating it."""

    namespace, document_key = _validate_identity(namespace, document_key)
    legacy_path = Path(legacy_path).resolve()
    if _read_json(legacy_path) is not _MISSING:
        return True
    database_path = database_path_for(legacy_path)
    if not database_path.exists():
        return False
    try:
        connection = _connect(database_path)
        try:
            row = connection.execute(
                """
                SELECT 1 FROM json_documents
                WHERE namespace = ? AND document_key = ?
                """,
                (namespace, document_key),
            ).fetchone()
            return row is not None
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False


def storage_status(legacy_path):
    """Return a compact health snapshot for diagnostics and tests."""

    database_path = database_path_for(legacy_path)
    try:
        connection = _connect(database_path)
        try:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            documents = connection.execute(
                "SELECT COUNT(*) FROM json_documents"
            ).fetchone()[0]
            migrations = connection.execute(
                "SELECT COUNT(*) FROM json_migrations"
            ).fetchone()[0]
            streams = connection.execute(
                "SELECT COUNT(*) FROM jsonl_streams"
            ).fetchone()[0]
            events = connection.execute(
                "SELECT COUNT(*) FROM jsonl_events"
            ).fetchone()[0]
            stream_migrations = connection.execute(
                "SELECT COUNT(*) FROM jsonl_migrations"
            ).fetchone()[0]
            return {
                "database": str(database_path),
                "schema_version": SCHEMA_VERSION,
                "quick_check": quick_check,
                "documents": documents,
                "migrations": migrations,
                "streams": streams,
                "events": events,
                "stream_migrations": stream_migrations,
            }
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as error:
        return {
            "database": str(database_path),
            "schema_version": SCHEMA_VERSION,
            "quick_check": "unavailable",
            "error": type(error).__name__,
        }
