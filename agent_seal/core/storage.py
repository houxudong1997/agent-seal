"""
Unified storage interface — pluggable backends.

Supports: JSONL (file), SQLite, PostgreSQL.
All backends implement the same Store protocol — swap without code changes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path

from ..config import config
from .chain import ChainEvent, SessionChain

logger = logging.getLogger(__name__)


# ═══════════════════════ ABSTRACT STORE ═══════════════════════


class AuditStore(ABC):
    """Abstract storage backend for audit trails."""

    @abstractmethod
    def write(self, event: ChainEvent) -> None: ...

    @abstractmethod
    def read_session(self, session_id: str) -> list[dict]: ...

    @abstractmethod
    def sessions(self) -> list[str]: ...

    @abstractmethod
    def stats(self) -> dict: ...

    @abstractmethod
    def verify_session(self, session_id: str) -> bool: ...

    @abstractmethod
    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query events with optional filters, returning (page, total_count).

        Filters are pushed down to the storage layer where possible
        (SQL WHERE clauses for SQL-based backends, early file skip for
        JSONL), avoiding the O(n²) pattern of loading every event into
        memory and then filtering in Python.
        """
        ...

    @abstractmethod
    def close(self) -> None: ...


# ═══════════════════════ JSONL BACKEND ═══════════════════════


class JSONLStore(AuditStore):
    """File-based JSON Lines storage. Best for write-heavy workloads."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.corrupt_lines: int = 0
        """Number of corrupt lines encountered during read operations (since last close)."""

    def write(self, event: ChainEvent) -> None:
        d = {
            "event_id": event.event_id,
            "session_id": event.session_id,
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "agent_id": event.agent_id,
            "prompt_version": event.prompt_version,
            "input_snapshot": event.input_snapshot,
            "output_snapshot": event.output_snapshot,
            "metadata": event.metadata,
            "prev_hash": event.prev_hash,
            "hash": event.hash,
        }
        filepath = self.dir / f"{event.session_id}.jsonl"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
        logger.debug(
            "JSONL write: session=%s event=%s seq=%d file=%s",
            event.session_id,
            event.event_id,
            event.sequence,
            filepath.name,
        )

    def read_session(self, session_id: str) -> list[dict]:
        f = self.dir / f"{session_id}.jsonl"
        if not f.exists():
            return []
        events = []
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        self.corrupt_lines += 1
                        # Truncate corrupt content to 200 chars to avoid log flooding
                        snippet = line[:200] + ("…" if len(line) > 200 else "")
                        logger.error(
                            "JSONL corrupt line #%d in session=%s file=%s: %r",
                            self.corrupt_lines,
                            session_id,
                            f.name,
                            snippet,
                        )
        return events

    def sessions(self) -> list[str]:
        return sorted([p.stem for p in self.dir.glob("*.jsonl")])

    def stats(self) -> dict:
        sids = self.sessions()
        total = 0
        types: dict[str, int] = {}
        for sid in sids:
            f = self.dir / f"{sid}.jsonl"
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        self.corrupt_lines += 1
                        # Truncate corrupt content to 200 chars to avoid log flooding
                        snippet = line[:200] + ("…" if len(line) > 200 else "")
                        logger.error(
                            "JSONL corrupt line #%d in session=%s file=%s: %r",
                            self.corrupt_lines,
                            sid,
                            f.name,
                            snippet,
                        )
                        continue
                    total += 1
                    t = e.get("event_type", "?")
                    types[t] = types.get(t, 0) + 1
        return {"total_events": total, "sessions": len(sids), "event_types": types}

    def verify_session(self, session_id: str) -> bool:
        data = self.read_session(session_id)
        chain = SessionChain.from_dicts(session_id, data)
        return chain.verify()

    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query events with optional filters.

        When ``session_id`` is provided, only that session's file is read.
        When ``session_id`` is None, **all JSONL files are loaded into
        memory** — this is O(n) in the total number of events across all
        sessions and may cause OOM on large datasets. Prefer the SQL-based
        backends for unbounded cross-session queries.
        """
        # JSONL: if session_id, read only that file; filter event_type in Python.
        if session_id:
            all_events = self.read_session(session_id)
        else:
            all_events = []
            for sid in self.sessions():
                all_events.extend(self.read_session(sid))

        if event_type:
            filtered = [e for e in all_events if e.get("event_type") == event_type]
        else:
            filtered = all_events

        total = len(filtered)
        page = filtered[offset : offset + limit]
        return page, total

    def close(self) -> None:
        self.corrupt_lines = 0


# ═══════════════════════ SQLITE BACKEND ═══════════════════════


class SQLiteStore(AuditStore):
    """SQLite storage. Best for read-heavy workloads (dashboards, search)."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL, session_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, timestamp REAL NOT NULL,
            event_type TEXT NOT NULL, agent_id TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_snapshot TEXT DEFAULT '', output_snapshot TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            prev_hash TEXT DEFAULT '', hash TEXT DEFAULT ''
        )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_session ON events(session_id)")
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_session_seq ON events(session_id,sequence)"
        )
        self._db.commit()
        self._columns = self._get_columns()

    def _get_columns(self) -> list[str]:
        """Return the column names for the events table (cached once at init)."""
        return [d[0] for d in self._db.execute("SELECT * FROM events LIMIT 0").description]

    def write(self, event: ChainEvent) -> None:
        self._db.execute(
            "INSERT INTO events(event_id,session_id,sequence,timestamp,event_type,agent_id,prompt_version,input_snapshot,output_snapshot,metadata_json,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event.event_id,
                event.session_id,
                event.sequence,
                event.timestamp,
                event.event_type,
                event.agent_id,
                event.prompt_version,
                event.input_snapshot[:8000],
                event.output_snapshot[:8000],
                json.dumps(event.metadata, ensure_ascii=False),
                event.prev_hash,
                event.hash,
            ),
        )
        self._db.commit()
        logger.debug(
            "SQLite write: session=%s event=%s seq=%d",
            event.session_id,
            event.event_id,
            event.sequence,
        )

    def read_session(self, session_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY sequence", (session_id,)
        ).fetchall()
        return [self._row_to_dict(dict(zip(self._columns, r, strict=True))) for r in rows]

    def sessions(self) -> list[str]:
        return [
            r[0]
            for r in self._db.execute(
                "SELECT DISTINCT session_id FROM events ORDER BY session_id"
            ).fetchall()
        ]

    def stats(self) -> dict:
        t = self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        s = self._db.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0]
        types = dict(
            self._db.execute(
                "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
            ).fetchall()
        )
        return {"total_events": t, "sessions": s, "event_types": types}

    def verify_session(self, session_id: str) -> bool:
        data = self.read_session(session_id)
        chain = SessionChain.from_dicts(session_id, data)
        return chain.verify()

    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """SQL query with WHERE clauses — filtering pushed to storage layer."""
        where_clauses: list[str] = []
        params: list = []

        if session_id is not None:
            where_clauses.append("session_id = ?")
            params.append(session_id)
        if event_type is not None:
            where_clauses.append("event_type = ?")
            params.append(event_type)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Get total matching rows
        count_sql = f"SELECT COUNT(*) FROM events {where_sql}"
        total = self._db.execute(count_sql, params).fetchone()[0]

        # Get page ordered by id DESC (most recent first)
        query_sql = f"SELECT * FROM events {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
        rows = self._db.execute(query_sql, [*params, limit, offset]).fetchall()

        return [self._row_to_dict(dict(zip(self._columns, r, strict=True))) for r in rows], total

    def close(self) -> None:
        self._db.close()

    def _row_to_dict(self, d: dict) -> dict:
        d.pop("id", None)
        try:
            d["metadata"] = json.loads(d.get("metadata_json", "{}") or "{}")
        except (json.JSONDecodeError, KeyError):
            d["metadata"] = {}
        return d


# ═══════════════════════ POSTGRESQL BACKEND ═══════════════════════


class PostgreSQLStore(AuditStore):
    """PostgreSQL storage backend. Production-grade, concurrent-safe.

    Uses native PostgreSQL types (JSONB for metadata, BIGSERIAL for id).
    Auto-creates the events table and indexes on first use.

    Requires psycopg2 (pip install psycopg2-binary).
    """

    def __init__(self, dsn: str):
        """Initialize PostgreSQL store.

        Args:
            dsn: PostgreSQL connection string, e.g.
                 ``postgresql://user:pass@host:5432/dbname``
        """
        try:
            import psycopg2
            import psycopg2.pool
        except ImportError:
            raise ImportError(
                "PostgreSQLStore requires psycopg2. Install with:\n  pip install psycopg2-binary"
            ) from None

        self._dsn = dsn
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=dsn)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create the events table and indexes if they don't exist."""
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
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
        finally:
            self._pool.putconn(conn)

    def write(self, event: ChainEvent) -> None:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO events"
                    "(event_id, session_id, sequence, timestamp, event_type,"
                    " agent_id, prompt_version, input_snapshot, output_snapshot,"
                    " metadata, prev_hash, hash)"
                    " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        event.event_id,
                        event.session_id,
                        event.sequence,
                        event.timestamp,
                        event.event_type,
                        event.agent_id,
                        event.prompt_version,
                        event.input_snapshot[:8000],
                        event.output_snapshot[:8000],
                        event.metadata
                        if isinstance(event.metadata, str)
                        else json.dumps(event.metadata),
                        event.prev_hash,
                        event.hash,
                    ),
                )
                conn.commit()
                logger.debug(
                    "PostgreSQL write: session=%s event=%s seq=%d",
                    event.session_id,
                    event.event_id,
                    event.sequence,
                )
        finally:
            self._pool.putconn(conn)

    def read_session(self, session_id: str) -> list[dict]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id, session_id, sequence, timestamp,"
                    " event_type, agent_id, prompt_version,"
                    " input_snapshot, output_snapshot,"
                    " metadata, prev_hash, hash"
                    " FROM events WHERE session_id = %s ORDER BY sequence",
                    (session_id,),
                )
                rows = cur.fetchall()
                assert cur.description is not None  # SELECT always returns description
                cols = [desc[0] for desc in cur.description]
                return [self._row_to_dict(dict(zip(cols, row, strict=True))) for row in rows]
        finally:
            self._pool.putconn(conn)

    def sessions(self) -> list[str]:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT session_id FROM events ORDER BY session_id")
                return [row[0] for row in cur.fetchall()]
        finally:
            self._pool.putconn(conn)

    def stats(self) -> dict:
        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM events")
                row = cur.fetchone()
                assert row is not None
                total = row[0]
                cur.execute("SELECT COUNT(DISTINCT session_id) FROM events")
                row2 = cur.fetchone()
                assert row2 is not None
                sessions = row2[0]
                cur.execute(
                    "SELECT event_type, COUNT(*) FROM events"
                    " GROUP BY event_type ORDER BY event_type"
                )
                types = dict(cur.fetchall())
                return {
                    "total_events": total,
                    "sessions": sessions,
                    "event_types": types,
                }
        finally:
            self._pool.putconn(conn)

    def verify_session(self, session_id: str) -> bool:
        data = self.read_session(session_id)
        chain = SessionChain.from_dicts(session_id, data)
        return chain.verify()

    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        # PostgreSQL query with WHERE clauses -- filtering pushed to storage layer.
        where_clauses: list[str] = []
        params: list = []

        if session_id is not None:
            where_clauses.append("session_id = %s")
            params.append(session_id)
        if event_type is not None:
            where_clauses.append("event_type = %s")
            params.append(event_type)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        conn = self._pool.getconn()
        try:
            with conn.cursor() as cur:
                # Get total matching rows
                count_sql = f"SELECT COUNT(*) FROM events {where_sql}"
                cur.execute(count_sql, params)
                total_row = cur.fetchone()
                assert total_row is not None  # COUNT always returns a row
                total = total_row[0]

                # Get page ordered by id DESC (most recent first)
                query_sql = (
                    f"SELECT event_id, session_id, sequence, timestamp,"
                    f" event_type, agent_id, prompt_version,"
                    f" input_snapshot, output_snapshot,"
                    f" metadata, prev_hash, hash"
                    f" FROM events {where_sql}"
                    f" ORDER BY id DESC LIMIT %s OFFSET %s"
                )
                cur.execute(query_sql, [*params, limit, offset])
                rows = cur.fetchall()
                assert cur.description is not None  # SELECT always returns description
                cols = [desc[0] for desc in cur.description]
                return [self._row_to_dict(dict(zip(cols, row, strict=True))) for row in rows], total
        finally:
            self._pool.putconn(conn)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None  # type: ignore[assignment]

    @staticmethod
    def _row_to_dict(d: dict) -> dict:
        """Convert a DB row dict to the standard format.

        PostgreSQL JSONB columns are returned as Python objects,
        so metadata is already a dict — no JSON parsing needed.
        """
        d.pop("id", None)
        # metadata is already a dict from JSONB — normalize
        meta = d.get("metadata")
        if isinstance(meta, str):
            try:
                d["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        elif meta is None:
            d["metadata"] = {}
        return d


# ═══════════════════════ POSTGRESQL BACKEND (SQLAlchemy) ══════


class PostgreSQLStoreORM(AuditStore):
    """PostgreSQL storage via SQLAlchemy ORM — for deployments using
    the full agent-seal data model (P1.1 schema with Alembic migrations).

    Prefer ``PostgreSQLStore`` for a lightweight, zero-ORM backend that
    matches the SQLiteStore design. Use this when you need the richer
    schema (UUID, INET, JSONB GIN indexes, etc.) managed by Alembic.
    """

    def __init__(self, db_url: str):
        try:
            from sqlalchemy import create_engine

            from ..models.event import Event
        except ImportError:
            raise ImportError(
                "PostgreSQLStoreORM requires SQLAlchemy. Install with:\n"
                "  pip install sqlalchemy psycopg2-binary"
            ) from None

        self._engine = create_engine(db_url, pool_size=5, max_overflow=10)
        self._Event = Event  # cache model ref

        # Ensure tables exist (idempotent)
        from ..models.base import Base

        Base.metadata.create_all(self._engine)

    def write(self, event: ChainEvent) -> None:
        import datetime as _dt
        import uuid as _uuid

        from sqlalchemy.orm import Session

        from ..models.event import Event as EventModel

        with Session(self._engine) as session:
            e = EventModel(
                event_id=_uuid.UUID(event.event_id) if len(event.event_id) == 36 else _uuid.uuid4(),
                session_id=event.session_id,
                sequence=event.sequence,
                timestamp=_dt.datetime.fromtimestamp(event.timestamp, tz=_dt.UTC),
                event_type=event.event_type,
                agent_id=event.agent_id,
                prompt_version=event.prompt_version,
                input_snapshot=event.input_snapshot[:8000],
                output_snapshot=event.output_snapshot[:8000],
                metadata_=event.metadata,
                prev_hash=event.prev_hash,
                hash=event.hash,
            )
            session.add(e)
            session.commit()
            logger.debug(
                "PostgreSQL(ORM) write: session=%s event=%s seq=%d",
                event.session_id,
                event.event_id,
                event.sequence,
            )

    def read_session(self, session_id: str) -> list[dict]:
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            stmt = (
                select(self._Event)
                .where(self._Event.session_id == session_id)
                .order_by(self._Event.sequence)
            )
            rows = session.execute(stmt).scalars().all()
            return [self._model_to_dict(r) for r in rows]

    def sessions(self) -> list[str]:
        from sqlalchemy import distinct, select
        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            stmt = select(distinct(self._Event.session_id)).order_by(self._Event.session_id)
            return [r[0] for r in session.execute(stmt).fetchall()]

    def stats(self) -> dict:
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            total = session.execute(select(func.count()).select_from(self._Event)).scalar()
            s = session.execute(select(func.count(func.distinct(self._Event.session_id)))).scalar()
            types_rows = session.execute(
                select(self._Event.event_type, func.count()).group_by(self._Event.event_type)
            ).fetchall()
            return {
                "total_events": total,
                "sessions": s,
                "event_types": dict(types_rows),
            }

    def verify_session(self, session_id: str) -> bool:
        data = self.read_session(session_id)
        chain = SessionChain.from_dicts(session_id, data)
        return chain.verify()

    def query_events(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        # SQLAlchemy ORM query with filters pushed to storage layer.
        from sqlalchemy import func, select
        from sqlalchemy.orm import Session

        with Session(self._engine) as session:
            stmt = select(self._Event)
            count_stmt = select(func.count()).select_from(self._Event)

            if session_id is not None:
                stmt = stmt.where(self._Event.session_id == session_id)
                count_stmt = count_stmt.where(self._Event.session_id == session_id)
            if event_type is not None:
                stmt = stmt.where(self._Event.event_type == event_type)
                count_stmt = count_stmt.where(self._Event.event_type == event_type)

            # Get total matching rows
            total = session.execute(count_stmt).scalar()

            # Get page ordered by id DESC (most recent first)
            stmt = stmt.order_by(self._Event.id.desc()).limit(limit).offset(offset)
            rows = session.execute(stmt).scalars().all()
            return [self._model_to_dict(r) for r in rows], total

    def close(self) -> None:
        self._engine.dispose()

    @staticmethod
    def _model_to_dict(model) -> dict:
        """Convert SQLAlchemy Event model to dict matching ChainEvent fields."""
        import datetime as _dt

        ts = model.timestamp
        if isinstance(ts, _dt.datetime):
            ts = ts.timestamp()

        return {
            "event_id": str(model.event_id)[:12],
            "session_id": model.session_id,
            "sequence": model.sequence,
            "timestamp": ts,
            "event_type": model.event_type,
            "agent_id": model.agent_id,
            "prompt_version": model.prompt_version,
            "input_snapshot": model.input_snapshot or "",
            "output_snapshot": model.output_snapshot or "",
            "metadata": model.metadata_ or {},
            "prev_hash": model.prev_hash or "",
            "hash": model.hash or "",
        }


# ═══════════════════════ STORE FACTORY ═══════════════════════


def create_store(uri: str, backend: str | None = None) -> AuditStore:
    """Create a store from a URI.

    Examples:
        create_store("jsonl://./audit_logs")        → JSONLStore
        create_store("sqlite://audit.db")            → SQLiteStore
        create_store("postgresql://user:pass@h/db")  → PostgreSQLStore
        create_store("postgresql://...", "orm")      → PostgreSQLStoreORM
        create_store("./audit_logs")                 → JSONLStore (default)
        create_store("audit.db")                     → SQLiteStore (.db extension)

    Args:
        uri: Storage URI — protocol prefix auto-detects backend.
        backend: Optional explicit override:
                 'jsonl' | 'sqlite' | 'postgresql' | 'postgresql-orm'
    """
    # Explicit backend override takes priority
    store: AuditStore
    if backend == "jsonl":
        target = uri.replace("jsonl://", "") if uri.startswith("jsonl://") else uri
        store = JSONLStore(target)
        logger.info("Store created: backend=JSONL dir=%s", target)
        return store
    if backend == "sqlite":
        target = uri.replace("sqlite://", "") if uri.startswith("sqlite://") else uri
        store = SQLiteStore(target)
        logger.info("Store created: backend=SQLite db=%s", target)
        return store
    if backend == "postgresql":
        store = PostgreSQLStore(uri)
        logger.info("Store created: backend=PostgreSQL")
        return store
    if backend in ("postgresql-orm", "postgres_orm"):
        store = PostgreSQLStoreORM(uri)
        logger.info("Store created: backend=PostgreSQL(ORM)")
        return store

    # Auto-detect from URI scheme
    if uri.startswith("jsonl://"):
        target = uri.replace("jsonl://", "")
        store = JSONLStore(target)
        logger.info("Store created (auto): backend=JSONL dir=%s", target)
        return store
    if uri.startswith("sqlite://"):
        target = uri.replace("sqlite://", "")
        store = SQLiteStore(target)
        logger.info("Store created (auto): backend=SQLite db=%s", target)
        return store
    if uri.startswith("postgresql://") or uri.startswith("postgres://"):
        store = PostgreSQLStore(uri)
        logger.info("Store created (auto): backend=PostgreSQL")
        return store
    if uri.endswith(".db") or uri.endswith(".sqlite"):
        store = SQLiteStore(uri)
        logger.info("Store created (auto): backend=SQLite path=%s", uri)
        return store
    store = JSONLStore(uri)
    logger.info("Store created (auto): backend=JSONL (default) dir=%s", uri)
    return store


# ═══════════════════════ HIGH-LEVEL ENGINE ═══════════════════════


class AuditEngine:
    """
    One API to rule them all. Uses a Store backend + SessionChains.

    Usage:
        engine = AuditEngine("sqlite://audit.db")
        engine.log("sess-1", "decision", "bot", "v1", "input", "output")
        engine.verify("sess-1")  # True
    """

    _MAX_ACTIVE_CHAINS = 10_000

    def __init__(self, store_uri: str | None = None):
        uri = store_uri or config.store_uri
        backend = config.storage_backend
        self._store_uri = uri
        self.store = create_store(uri, backend=backend if backend != "auto" else None)
        self._active_chains: dict[str, SessionChain] = {}
        self._chain_lru: list[str] = []  # Most recently used at end

    @property
    def store_uri(self) -> str:
        """The resolved store URI used by this engine."""
        return self._store_uri

    def log(
        self,
        session_id: str,
        event_type: str,
        agent_id: str,
        prompt_version: str,
        input_text: str,
        output_text: str,
        metadata: dict | None = None,
    ) -> ChainEvent:
        """Log an event. Auto-creates or reuses the session chain."""
        is_new = session_id not in self._active_chains
        if is_new:
            # Load existing events from store
            existing = self.store.read_session(session_id)
            chain = SessionChain.from_dicts(session_id, existing)
            self._active_chains[session_id] = chain
            self._chain_lru.append(session_id)
            # Evict least recently used chain if over capacity
            while len(self._active_chains) > self._MAX_ACTIVE_CHAINS:
                evict_sid = self._chain_lru.pop(0)
                if evict_sid in self._active_chains:
                    del self._active_chains[evict_sid]
                    logger.debug(
                        "AuditEngine: evicted LRU chain session=%s (active=%d)",
                        evict_sid,
                        len(self._active_chains),
                    )
            logger.debug(
                "AuditEngine: loaded session=%s existing_events=%d",
                session_id,
                len(existing),
            )
        else:
            # Move to end of LRU list (most recently used)
            self._chain_lru.remove(session_id)
            self._chain_lru.append(session_id)

        chain = self._active_chains[session_id]
        event = chain.append(
            event_type, agent_id, prompt_version, input_text, output_text, metadata
        )
        self.store.write(event)
        logger.info(
            "AuditEngine: logged event session=%s type=%s agent=%s seq=%d chain_len=%d",
            session_id,
            event_type,
            agent_id,
            event.sequence,
            len(chain.events),
        )
        return event

    def verify(self, session_id: str | None = None) -> bool:
        """Verify chain integrity. If session_id is None, verify ALL sessions."""
        if session_id:
            ok = self.store.verify_session(session_id)
            logger.info(
                "AuditEngine verify session=%s: %s",
                session_id,
                "OK" if ok else "FAILED",
            )
            return ok
        for sid in self.store.sessions():
            if not self.store.verify_session(sid):
                logger.error("AuditEngine verify ALL: session=%s FAILED", sid)
                return False
        logger.info("AuditEngine verify ALL: OK")
        return True

    def read(self, session_id: str) -> list[dict]:
        return self.store.read_session(session_id)

    def sessions(self) -> list[str]:
        return self.store.sessions()

    def stats(self) -> dict:
        return self.store.stats()

    def query(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Query events with filters pushed to storage. Returns (page, total_count)."""
        return self.store.query_events(session_id, event_type, limit, offset)

    def close(self):
        self.store.close()
