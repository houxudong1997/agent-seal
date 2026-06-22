"""
Migration tools: JSONL ↔ SQLite ↔ PostgreSQL.

Phase 1.5 adds JSONL→PostgreSQL and SQLite→PostgreSQL migration paths
alongside the existing JSONL↔SQLite functions.

All PostgreSQL functions auto-create the events table if it doesn't exist,
matching the PostgreSQLStore schema from core/storage.py.
"""

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .storage import SQLiteTrail

logger = logging.getLogger(__name__)

# ── Batch size for PostgreSQL bulk inserts ──
_BATCH_SIZE = 1000


# ═══════════════════════ JSONL ↔ SQLITE (existing) ═══════════════════════


def jsonl_to_sqlite(jsonl_dir: str | Path, db_path: str | Path) -> int:
    """
    Migrate from JSONL audit trail to SQLite.

    Returns number of events migrated.
    """
    jsonl_dir = Path(jsonl_dir)
    jsonl_file = jsonl_dir / "audit.jsonl"

    if not jsonl_file.exists():
        raise FileNotFoundError(f"No audit trail found at {jsonl_file}")

    sqlite = SQLiteTrail(db_path)
    count = 0

    with open(jsonl_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            sqlite.log(
                session_id=event.get("session_id", ""),
                event_type=event.get("event_type", ""),
                agent_id=event.get("agent_id", ""),
                prompt_version=event.get("prompt_version", ""),
                input_snapshot=event.get("input_snapshot", ""),
                output_snapshot=event.get("output_snapshot", ""),
                metadata=event.get("metadata", {}),
            )
            count += 1

    return count


def sqlite_to_jsonl(db_path: str | Path, output_dir: str | Path) -> int:
    """Export SQLite to JSONL format. Returns event count."""
    sqlite = SQLiteTrail(db_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    sqlite.export_jsonl(out / "audit.jsonl")
    return int(sqlite.stats()["total_events"])


# ═══════════════════════ JSONL → POSTGRESQL ═══════════════════════


def jsonl_to_postgres(
    jsonl_dir: str | Path,
    pg_dsn: str,
    *,
    drop_existing: bool = False,
) -> int:
    """
    Migrate from JSONL audit trail to PostgreSQL.

    Supports two JSONL formats (auto-detected):

    - **Old-style**: single ``audit.jsonl`` file where each line is a flat
      event dict with ``session_id``, ``event_type``, ``agent_id``, etc.
    - **New-style** (per-session): directory of ``{session_id}.jsonl`` files
      where each line is a full ``ChainEvent`` dict with ``sequence``,
      ``prev_hash``, ``hash``.

    The target PostgreSQL table uses the same schema as ``PostgreSQLStore``
    from ``core/storage.py`` (``BIGSERIAL`` id, ``JSONB`` metadata).

    Args:
        jsonl_dir: Directory containing JSONL audit data.
        pg_dsn: PostgreSQL connection string, e.g.
                ``postgresql://user:***@host:5432/dbname``.
        drop_existing: If ``True``, DROP the events table before migration
                       (dangerous — off by default).

    Returns:
        Number of events migrated.

    Raises:
        ImportError: If ``psycopg2`` is not installed.
        FileNotFoundError: If no JSONL files were found in ``jsonl_dir``.
    """
    _ensure_psycopg2()

    jsonl_dir = Path(jsonl_dir)
    events = _read_jsonl_events(jsonl_dir)

    if not events:
        raise FileNotFoundError(f"No JSONL audit data found in {jsonl_dir}")

    return _write_pg(pg_dsn, events, drop_existing=drop_existing)


# ═══════════════════════ SQLITE → POSTGRESQL ═══════════════════════


def sqlite_to_postgres(
    db_path: str | Path,
    pg_dsn: str,
    *,
    drop_existing: bool = False,
    table: str = "events",
) -> int:
    """
    Migrate from SQLite audit trail to PostgreSQL.

    Auto-detects the SQLite schema version:

    - **Old-style** (``SQLiteTrail``): no ``sequence`` column — sequence is
      generated from event ordering within each session.
    - **New-style** (``SQLiteStore``): has ``sequence`` column — used
      directly.

    Args:
        db_path: Path to the SQLite database file.
        pg_dsn: PostgreSQL connection string.
        drop_existing: If ``True``, DROP the events table before migration.
        table: Name of the SQLite table to read (default ``events``).

    Returns:
        Number of events migrated.

    Raises:
        ImportError: If ``psycopg2`` is not installed.
        FileNotFoundError: If ``db_path`` does not exist.
    """
    _ensure_psycopg2()

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    events = _read_sqlite_events(db_path, table=table)

    if not events:
        logger.warning("No events found in SQLite table %s", table)
        return 0

    return _write_pg(pg_dsn, events, drop_existing=drop_existing)


# ═══════════════════════ INTERNAL HELPERS ═══════════════════════


def _ensure_psycopg2() -> None:
    """Raise ImportError with a helpful message if psycopg2 is missing."""
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        raise ImportError(
            "PostgreSQL migration requires psycopg2. Install with:\n  pip install psycopg2-binary"
        ) from None


def _read_jsonl_events(jsonl_dir: Path) -> list[dict[str, Any]]:
    """
    Auto-detect JSONL format and read all events.

    Returns a list of normalized event dicts (all ChainEvent fields present).
    """
    old_style_file = jsonl_dir / "audit.jsonl"

    if old_style_file.exists():
        logger.info("Detected old-style JSONL: single audit.jsonl")
        return _read_old_jsonl(old_style_file)

    # New-style: per-session .jsonl files
    session_files = sorted(jsonl_dir.glob("*.jsonl"))
    if not session_files:
        return []

    logger.info(
        "Detected new-style JSONL: %d session file(s)",
        len(session_files),
    )
    events: list[dict[str, Any]] = []
    for sf in session_files:
        events.extend(_read_new_jsonl_file(sf))

    return events


def _read_old_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Read old-style audit.jsonl (flat event dicts, no sequence field).

    Generates missing fields (event_id, sequence, timestamp, prev_hash,
    hash) so the output is compatible with the PostgreSQL schema.
    """
    raw_events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw_events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line in %s", path.name)
                continue

    if not raw_events:
        return []

    # Group by session_id to compute per-session sequences.
    # Preserve original order within each session group (stable sort).
    by_session: dict[str, list[dict[str, Any]]] = {}
    for e in raw_events:
        sid = e.get("session_id", "")
        by_session.setdefault(sid, []).append(e)

    # Normalize: add missing fields, assign sequence
    result: list[dict[str, Any]] = []
    for _sid, group in by_session.items():
        # Sort by timestamp if available, otherwise keep insertion order
        group.sort(key=lambda x: x.get("timestamp", 0))
        for seq, e in enumerate(group):
            result.append(_normalize_old_event(e, seq))

    return result


def _normalize_old_event(raw: dict[str, Any], sequence: int) -> dict[str, Any]:
    """Fill in missing ChainEvent fields for an old-format event."""
    return {
        "event_id": raw.get("event_id") or str(uuid.uuid4())[:12],
        "session_id": raw.get("session_id", ""),
        "sequence": sequence,
        "timestamp": raw.get("timestamp", time.time()),
        "event_type": raw.get("event_type", ""),
        "agent_id": raw.get("agent_id", ""),
        "prompt_version": raw.get("prompt_version", ""),
        "input_snapshot": raw.get("input_snapshot", "")[:8000],
        "output_snapshot": raw.get("output_snapshot", "")[:8000],
        "metadata": raw.get("metadata", {}) or {},
        "prev_hash": raw.get("prev_hash", ""),
        "hash": raw.get("hash", ""),
    }


def _read_new_jsonl_file(path: Path) -> list[dict[str, Any]]:
    """
    Read a new-style per-session JSONL file.

    Events already have ChainEvent fields; we only filter to valid fields
    and fill in any that are unexpectedly missing.
    """
    valid_fields = frozenset(
        {
            "event_id",
            "session_id",
            "sequence",
            "timestamp",
            "event_type",
            "agent_id",
            "prompt_version",
            "input_snapshot",
            "output_snapshot",
            "metadata",
            "prev_hash",
            "hash",
        }
    )

    events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON line in %s", path.name)
                continue

            # Strip storage-only fields (id, metadata_json, etc.)
            event = {k: v for k, v in raw.items() if k in valid_fields}

            # Fill defaults for any missing fields
            event.setdefault("event_id", str(uuid.uuid4())[:12])
            event.setdefault("session_id", "")
            event.setdefault("sequence", 0)
            event.setdefault("timestamp", time.time())
            event.setdefault("event_type", "")
            event.setdefault("agent_id", "")
            event.setdefault("prompt_version", "")
            event.setdefault("input_snapshot", "")
            event.setdefault("output_snapshot", "")
            event.setdefault("metadata", {})
            event.setdefault("prev_hash", "")
            event.setdefault("hash", "")

            events.append(event)

    return events


def _read_sqlite_events(db_path: Path, table: str = "events") -> list[dict[str, Any]]:
    """
    Read all events from a SQLite database, auto-detecting schema version.

    Old SQLiteTrail schema: no ``sequence`` column — generates it.
    New SQLiteStore schema: has ``sequence`` column — uses it directly.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return _read_sqlite_events_inner(conn, table)
    finally:
        conn.close()


def _read_sqlite_events_inner(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Core SQLite read logic with an open connection."""
    # Check if the table exists
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    if cursor.fetchone() is None:
        raise ValueError(f"Table '{table}' not found in SQLite database")

    # Detect schema: old (no sequence column) vs new (has sequence)
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    has_sequence = "sequence" in cols

    if has_sequence:
        logger.info("Detected new-style SQLite schema (has sequence column)")
        return _read_sqlite_new_schema(conn, table, cols)
    else:
        logger.info("Detected old-style SQLite schema (no sequence column)")
        return _read_sqlite_old_schema(conn, table, cols)


def _read_sqlite_new_schema(
    conn: sqlite3.Connection, table: str, cols: list[str]
) -> list[dict[str, Any]]:
    """Read events from new-style SQLiteStore schema."""
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY session_id, sequence").fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d.pop("id", None)

        # Parse metadata_json if present (SQLite stores it as TEXT)
        meta = d.pop("metadata_json", None)
        if meta is not None:
            try:
                d["metadata"] = json.loads(meta) if isinstance(meta, str) else meta
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        elif "metadata" not in d:
            d["metadata"] = {}

        # Fill defaults
        d.setdefault("sequence", 0)
        d.setdefault("timestamp", time.time())
        d.setdefault("prev_hash", "")
        d.setdefault("hash", "")

        events.append(d)

    return events


def _read_sqlite_old_schema(
    conn: sqlite3.Connection, table: str, cols: list[str]
) -> list[dict[str, Any]]:
    """
    Read events from old-style SQLiteTrail schema (no sequence column).

    Generates per-session sequence numbers based on event ordering (by id).
    """
    rows = conn.execute(f"SELECT * FROM {table} ORDER BY session_id, id").fetchall()

    # Group by session_id to compute per-session sequences
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        d = dict(row)
        d.pop("id", None)

        # Parse metadata_json
        meta = d.pop("metadata_json", None)
        if meta is not None:
            try:
                d["metadata"] = json.loads(meta) if isinstance(meta, str) else meta
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        elif "metadata" not in d:
            d["metadata"] = {}

        sid = d.get("session_id", "")
        by_session.setdefault(sid, []).append(d)

    result: list[dict[str, Any]] = []
    for _sid, group in by_session.items():
        for seq, event in enumerate(group):
            event["sequence"] = seq
            event.setdefault("prev_hash", "")
            event.setdefault("hash", "")
            result.append(event)

    return result


def _write_pg(
    dsn: str,
    events: list[dict[str, Any]],
    *,
    drop_existing: bool = False,
) -> int:
    """
    Write events to PostgreSQL using batch inserts.

    Auto-creates the ``events`` table if it doesn't exist.  Uses
    ``execute_values`` for efficient bulk insertion.

    Returns the number of events written.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(dsn)
    try:
        _ensure_pg_schema(conn, drop_existing=drop_existing)
        count = _batch_insert_pg(conn, events)

        conn.commit()
        logger.info("Migrated %d events to PostgreSQL", count)
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_pg_schema(conn, *, drop_existing: bool = False) -> None:
    """
    Create the events table and indexes if they don't exist.

    Schema matches ``PostgreSQLStore._init_schema()`` from core/storage.py.
    """
    with conn.cursor() as cur:
        if drop_existing:
            cur.execute("DROP TABLE IF EXISTS events CASCADE")
            logger.warning("Dropped existing events table")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id BIGSERIAL PRIMARY KEY,
                event_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                timestamp DOUBLE PRECISION NOT NULL,
                event_type TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                prompt_version TEXT NOT NULL DEFAULT '',
                input_snapshot TEXT DEFAULT '',
                output_snapshot TEXT DEFAULT '',
                metadata JSONB DEFAULT '{}',
                prev_hash TEXT DEFAULT '',
                hash TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_session_seq "
            "ON events(session_id, sequence)"
        )
        conn.commit()


def _batch_insert_pg(conn, events: list[dict[str, Any]]) -> int:
    """
    Batch-insert events into PostgreSQL using execute_values.

    Uses INSERT ... ON CONFLICT DO NOTHING to gracefully skip duplicates
    on the (session_id, sequence) unique index.
    """
    import psycopg2.extras

    if not events:
        return 0

    # Convert metadata dicts to JSON strings for psycopg2 JSONB
    rows: list[tuple] = []
    for e in events:
        meta = e.get("metadata", {})
        if isinstance(meta, dict):
            meta_json = json.dumps(meta, ensure_ascii=False)
        else:
            meta_json = json.dumps({})

        rows.append(
            (
                e.get("event_id", "") or str(uuid.uuid4())[:12],
                e.get("session_id", ""),
                e.get("sequence", 0),
                e.get("timestamp", time.time()),
                e.get("event_type", ""),
                e.get("agent_id", ""),
                e.get("prompt_version", ""),
                (e.get("input_snapshot", "") or "")[:8000],
                (e.get("output_snapshot", "") or "")[:8000],
                meta_json,
                e.get("prev_hash", ""),
                e.get("hash", ""),
            )
        )

    sql = """
        INSERT INTO events (
            event_id, session_id, sequence, timestamp,
            event_type, agent_id, prompt_version,
            input_snapshot, output_snapshot,
            metadata, prev_hash, hash
        ) VALUES %s
        ON CONFLICT (session_id, sequence) DO NOTHING
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            sql,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=_BATCH_SIZE,
        )
        inserted = cur.rowcount

    return int(inserted or 0)
