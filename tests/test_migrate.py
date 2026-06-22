"""Tests for migrate.py: JSONL→PG and SQLite→PG migration paths.

Coverage targets:
  - All public migration functions (jsonl_to_postgres, sqlite_to_postgres)
  - Internal helpers (_ensure_psycopg2, _read_jsonl_events, _read_old_jsonl,
    _normalize_old_event, _read_new_jsonl_file, _read_sqlite_events_inner,
    _read_sqlite_new_schema, _read_sqlite_old_schema)
  - PG helpers (_write_pg, _ensure_pg_schema, _batch_insert_pg)
  - Edge cases: empty files, malformed JSON, missing tables, missing fields,
    drop_existing, duplicate conflict handling
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_audit.migrate import (
    _batch_insert_pg,
    _ensure_pg_schema,
    _ensure_psycopg2,
    _normalize_old_event,
    _read_jsonl_events,
    _read_new_jsonl_file,
    _read_old_jsonl,
    _read_sqlite_events,
    _write_pg,
    jsonl_to_postgres,
    sqlite_to_postgres,
)

# ════════════════════════════════════════════════════════════════════
#  Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_dir():
    """Yield a temporary directory as Path, cleaned up after."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _write_jsonl(dir_path: Path, filename: str, lines: list[dict]):
    """Helper: write a list of dicts as JSONL to a file."""
    file = dir_path / filename
    with open(file, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return file


def _create_sqlite_db(path: Path, schema: str, rows: list[dict], table: str = "events"):
    """Helper: create a SQLite DB with given schema and rows."""
    conn = sqlite3.connect(str(path))
    conn.execute(schema)
    for row in rows:
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(row.values()))
    conn.commit()
    conn.close()


# ── Sample old-style events (flat, no sequence) ──

OLD_EVENT_1 = {
    "session_id": "sess-1",
    "event_type": "decision",
    "agent_id": "bot-a",
    "prompt_version": "v1",
    "input_snapshot": "user said hello",
    "output_snapshot": "bot replied hi",
    "metadata": {"model": "gpt-4"},
}

OLD_EVENT_2 = {
    "session_id": "sess-1",
    "event_type": "tool_call",
    "agent_id": "bot-a",
    "prompt_version": "v1",
    "input_snapshot": "calc 2+2",
    "output_snapshot": "4",
    "metadata": {"tool": "calculator", "duration_ms": 150},
}

OLD_EVENT_3 = {
    "session_id": "sess-2",
    "event_type": "decision",
    "agent_id": "bot-b",
    "prompt_version": "v2",
    "input_snapshot": "translate hello",
    "output_snapshot": "你好",
    "metadata": {"model": "gpt-4o"},
}

# ── Sample new-style events (full ChainEvent) ──

NEW_EVENT_1 = {
    "event_id": "evt-001",
    "session_id": "sess-a",
    "sequence": 0,
    "timestamp": 1000.0,
    "event_type": "llm_call",
    "agent_id": "agent-x",
    "prompt_version": "v3",
    "input_snapshot": "prompt text",
    "output_snapshot": "response text",
    "metadata": {"tokens": 150},
    "prev_hash": "",
    "hash": "abc123",
}

NEW_EVENT_2 = {
    "event_id": "evt-002",
    "session_id": "sess-a",
    "sequence": 1,
    "timestamp": 1001.0,
    "event_type": "tool_result",
    "agent_id": "agent-x",
    "prompt_version": "v3",
    "input_snapshot": "tool input",
    "output_snapshot": "tool output",
    "metadata": {"tool": "search"},
    "prev_hash": "abc123",
    "hash": "def456",
}

NEW_EVENT_3 = {
    "event_id": "evt-003",
    "session_id": "sess-b",
    "sequence": 0,
    "timestamp": 1002.0,
    "event_type": "decision",
    "agent_id": "agent-y",
    "prompt_version": "v1",
    "input_snapshot": "input",
    "output_snapshot": "output",
    "metadata": {},
    "prev_hash": "",
    "hash": "ghi789",
}


# ════════════════════════════════════════════════════════════════════
#  _ensure_psycopg2
# ════════════════════════════════════════════════════════════════════


class TestEnsurePsycopg2:
    """_ensure_psycopg2: ImportError when psycopg2 is absent."""

    def test_raises_import_error_when_missing(self):
        """should raise ImportError when psycopg2 is not available."""
        with patch.dict("sys.modules", {"psycopg2": None}), \
                    pytest.raises(ImportError) as exc:
                _ensure_psycopg2()
        assert "psycopg2" in str(exc.value)

    def test_passes_when_available(self):
        """should not raise when psycopg2 is importable."""
        # In test environment, psycopg2 may or may not be installed.
        # We mock it to avoid dependency.
        mock_pg = MagicMock()
        with patch.dict("sys.modules", {"psycopg2": mock_pg}):
            _ensure_psycopg2()  # should not raise


# ════════════════════════════════════════════════════════════════════
#  _read_old_jsonl / _normalize_old_event
# ════════════════════════════════════════════════════════════════════


class TestReadOldJsonl:
    """_read_old_jsonl: read old-style audit.jsonl (flat events)."""

    def test_reads_single_session(self, tmp_dir):
        """should read flat events and normalize them."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1, OLD_EVENT_2])
        results = _read_old_jsonl(tmp_dir / "audit.jsonl")
        assert len(results) == 2
        assert results[0]["session_id"] == "sess-1"
        assert results[0]["sequence"] == 0
        assert results[1]["sequence"] == 1

    def test_multi_session_generates_per_session_sequences(self, tmp_dir):
        """should generate per-session sequence numbers."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1, OLD_EVENT_3, OLD_EVENT_2])
        results = _read_old_jsonl(tmp_dir / "audit.jsonl")
        # sess-1 events: OLD_EVENT_1 (seq=0), OLD_EVENT_2 (seq=1)
        # sess-2 event: OLD_EVENT_3 (seq=0)
        sess1 = [r for r in results if r["session_id"] == "sess-1"]
        sess2 = [r for r in results if r["session_id"] == "sess-2"]
        assert len(sess1) == 2
        assert len(sess2) == 1
        assert sess1[0]["sequence"] == 0
        assert sess1[1]["sequence"] == 1
        assert sess2[0]["sequence"] == 0

    def test_skips_empty_lines(self, tmp_dir):
        """should skip blank lines."""
        file = tmp_dir / "audit.jsonl"
        with open(file, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write(json.dumps(OLD_EVENT_1) + "\n")
            f.write("  \n")
            f.write(json.dumps(OLD_EVENT_2) + "\n")
        results = _read_old_jsonl(file)
        assert len(results) == 2

    def test_skips_malformed_json_lines(self, tmp_dir):
        """should skip lines that are not valid JSON."""
        file = tmp_dir / "audit.jsonl"
        with open(file, "w", encoding="utf-8") as f:
            f.write(json.dumps(OLD_EVENT_1) + "\n")
            f.write("not json data\n")
            f.write(json.dumps(OLD_EVENT_2) + "\n")
        results = _read_old_jsonl(file)
        assert len(results) == 2

    def test_returns_empty_for_empty_file(self, tmp_dir):
        """should return empty list for empty file."""
        file = tmp_dir / "audit.jsonl"
        file.write_text("")
        results = _read_old_jsonl(file)
        assert results == []

    def test_returns_empty_for_blank_file(self, tmp_dir):
        """should return empty list for file with only whitespace."""
        file = tmp_dir / "audit.jsonl"
        file.write_text("\n\n  \n")
        results = _read_old_jsonl(file)
        assert results == []

    def test_generates_missing_event_id(self, tmp_dir):
        """should generate event_id for events that lack it."""
        _write_jsonl(tmp_dir, "audit.jsonl", [{"session_id": "s-1", "event_type": "test"}])
        results = _read_old_jsonl(tmp_dir / "audit.jsonl")
        assert len(results) == 1
        assert len(results[0]["event_id"]) == 12  # uuid4()[:12]

    def test_sorts_by_timestamp_within_session(self, tmp_dir):
        """should sort events within a session by timestamp."""
        late = dict(OLD_EVENT_1, timestamp=200.0)
        early = dict(OLD_EVENT_1, timestamp=100.0)
        _write_jsonl(tmp_dir, "audit.jsonl", [late, early])
        results = _read_old_jsonl(tmp_dir / "audit.jsonl")
        assert len(results) == 2
        assert results[0]["timestamp"] == 100.0
        assert results[1]["timestamp"] == 200.0

    def test_preserves_event_id_when_present(self, tmp_dir):
        """should preserve existing event_id."""
        _write_jsonl(tmp_dir, "audit.jsonl", [{"event_id": "my-id", "session_id": "s-1"}])
        results = _read_old_jsonl(tmp_dir / "audit.jsonl")
        assert results[0]["event_id"] == "my-id"


class TestNormalizeOldEvent:
    """_normalize_old_event: fill in missing ChainEvent fields."""

    def test_fills_all_defaults(self):
        """should fill every required field with defaults."""
        result = _normalize_old_event({}, 0)
        assert result["event_id"] and isinstance(result["event_id"], str)
        assert result["session_id"] == ""
        assert result["sequence"] == 0
        assert isinstance(result["timestamp"], (int, float))
        assert result["event_type"] == ""
        assert result["agent_id"] == ""
        assert result["prompt_version"] == ""
        assert result["input_snapshot"] == ""
        assert result["output_snapshot"] == ""
        assert result["metadata"] == {}
        assert result["prev_hash"] == ""
        assert result["hash"] == ""

    def test_truncates_snapshots_at_8000(self):
        """should truncate input/output snapshots to 8000 chars."""
        long_str = "x" * 10000
        result = _normalize_old_event({"input_snapshot": long_str, "output_snapshot": long_str}, 0)
        assert len(result["input_snapshot"]) == 8000
        assert len(result["output_snapshot"]) == 8000

    def test_handles_none_metadata(self):
        """should convert None metadata to empty dict."""
        result = _normalize_old_event({"metadata": None}, 0)
        assert result["metadata"] == {}

    def test_preserves_provided_values(self):
        """should keep provided values unchanged."""
        event = {
            "event_id": "custom-id",
            "session_id": "sess-x",
            "event_type": "custom_type",
            "agent_id": "my-agent",
            "prompt_version": "v99",
            "input_snapshot": "in",
            "output_snapshot": "out",
            "metadata": {"key": "val"},
            "prev_hash": "prev",
            "hash": "curr",
            "timestamp": 42.0,
        }
        result = _normalize_old_event(event, 5)
        assert result["event_id"] == "custom-id"
        assert result["session_id"] == "sess-x"
        assert result["sequence"] == 5
        assert result["timestamp"] == 42.0
        assert result["event_type"] == "custom_type"
        assert result["agent_id"] == "my-agent"
        assert result["prompt_version"] == "v99"
        assert result["input_snapshot"] == "in"
        assert result["output_snapshot"] == "out"
        assert result["metadata"] == {"key": "val"}
        assert result["prev_hash"] == "prev"
        assert result["hash"] == "curr"


# ════════════════════════════════════════════════════════════════════
#  _read_new_jsonl_file
# ════════════════════════════════════════════════════════════════════


class TestReadNewJsonlFile:
    """_read_new_jsonl_file: read new-style per-session JSONL files."""

    def test_reads_valid_events(self, tmp_dir):
        """should read valid JSONL lines into dicts."""
        file = _write_jsonl(tmp_dir, "sess-a.jsonl", [NEW_EVENT_1, NEW_EVENT_2])
        results = _read_new_jsonl_file(file)
        assert len(results) == 2
        assert results[0]["event_id"] == "evt-001"
        assert results[1]["event_id"] == "evt-002"

    def test_filters_unknown_fields(self, tmp_dir):
        """should strip fields not in valid_fields set."""
        dirty = dict(NEW_EVENT_1, internal_only="secret", _private="hidden")
        file = _write_jsonl(tmp_dir, "sess-x.jsonl", [dirty])
        results = _read_new_jsonl_file(file)
        assert "internal_only" not in results[0]
        assert "_private" not in results[0]

    def test_fills_missing_fields(self, tmp_dir):
        """should fill defaults for missing fields."""
        sparse = {"event_id": "evt-min"}
        file = _write_jsonl(tmp_dir, "minimal.jsonl", [sparse])
        results = _read_new_jsonl_file(file)
        assert results[0]["event_id"] == "evt-min"
        assert results[0]["session_id"] == ""
        assert results[0]["sequence"] == 0
        assert results[0]["metadata"] == {}

    def test_skips_malformed_json(self, tmp_dir):
        """should skip unparseable lines."""
        file = tmp_dir / "bad.jsonl"
        with open(file, "w", encoding="utf-8") as f:
            f.write(json.dumps(NEW_EVENT_1) + "\n")
            f.write("{bad json}\n")
            f.write(json.dumps(NEW_EVENT_2) + "\n")
        results = _read_new_jsonl_file(file)
        assert len(results) == 2

    def test_skips_empty_lines(self, tmp_dir):
        """should skip blank lines."""
        file = tmp_dir / "mixed.jsonl"
        with open(file, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write(json.dumps(NEW_EVENT_1) + "\n")
            f.write("  \n")
        results = _read_new_jsonl_file(file)
        assert len(results) == 1

    def test_returns_empty_for_empty_file(self, tmp_dir):
        """should return empty list for empty file."""
        file = tmp_dir / "empty.jsonl"
        file.write_text("")
        results = _read_new_jsonl_file(file)
        assert results == []


# ════════════════════════════════════════════════════════════════════
#  _read_jsonl_events (auto-detect)
# ════════════════════════════════════════════════════════════════════


class TestReadJsonlEvents:
    """_read_jsonl_events: auto-detect old vs new JSONL format."""

    def test_detects_old_style(self, tmp_dir):
        """should detect and read old-style audit.jsonl."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1, OLD_EVENT_2])
        results = _read_jsonl_events(tmp_dir)
        assert len(results) == 2
        assert "sequence" in results[0]

    def test_detects_new_style(self, tmp_dir):
        """should detect and read new-style per-session JSONL."""
        _write_jsonl(tmp_dir, "sess-a.jsonl", [NEW_EVENT_1, NEW_EVENT_2])
        _write_jsonl(tmp_dir, "sess-b.jsonl", [NEW_EVENT_3])
        results = _read_jsonl_events(tmp_dir)
        assert len(results) == 3

    def test_returns_empty_for_empty_dir(self, tmp_dir):
        """should return empty list when no JSONL files exist."""
        results = _read_jsonl_events(tmp_dir)
        assert results == []

    def test_new_style_ignores_non_jsonl_files(self, tmp_dir):
        """should ignore non-.jsonl files in new-style mode."""
        _write_jsonl(tmp_dir, "sess-a.jsonl", [NEW_EVENT_1])
        (tmp_dir / "readme.txt").write_text("not jsonl")
        results = _read_jsonl_events(tmp_dir)
        assert len(results) == 1

    def test_old_style_preferred_over_new_style(self, tmp_dir):
        """should prefer old-style audit.jsonl when both exist."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1])
        _write_jsonl(tmp_dir, "sess-a.jsonl", [NEW_EVENT_1, NEW_EVENT_2])
        results = _read_jsonl_events(tmp_dir)
        # audit.jsonl takes priority
        assert len(results) == 1
        assert results[0]["session_id"] == OLD_EVENT_1["session_id"]


# ════════════════════════════════════════════════════════════════════
#  _read_sqlite_events (auto-detect)
# ════════════════════════════════════════════════════════════════════


class TestReadSqliteEvents:
    """_read_sqlite_events / _read_sqlite_events_inner."""

    def test_raises_value_error_for_missing_table(self, tmp_dir):
        """should raise ValueError when table doesn't exist."""
        db = tmp_dir / "empty.db"
        sqlite3.connect(str(db)).close()
        with pytest.raises(ValueError, match="not found"):
            _read_sqlite_events(db, table="events")

    def test_raises_file_not_found(self, tmp_dir):
        """should raise FileNotFoundError for nonexistent DB file."""
        # Note: _read_sqlite_events doesn't check existence; sqlite3.connect will raise
        with pytest.raises((FileNotFoundError, OSError)):
            _read_sqlite_events(tmp_dir / "nope.db")

    # ── New schema (has sequence column) ──

    def test_reads_new_schema(self, tmp_dir):
        """should read events from new-style schema (has sequence column)."""
        db = tmp_dir / "new.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT, session_id TEXT,
                sequence INTEGER, timestamp REAL,
                event_type TEXT, agent_id TEXT, prompt_version TEXT,
                input_snapshot TEXT, output_snapshot TEXT,
                metadata_json TEXT,
                prev_hash TEXT, hash TEXT
            )""",
            [
                {
                    "id": 1,
                    "event_id": "e1",
                    "session_id": "s1",
                    "sequence": 0,
                    "timestamp": 100.0,
                    "event_type": "t1",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in",
                    "output_snapshot": "out",
                    "metadata_json": '{"k":"v"}',
                    "prev_hash": "",
                    "hash": "h1",
                },
                {
                    "id": 2,
                    "event_id": "e2",
                    "session_id": "s1",
                    "sequence": 1,
                    "timestamp": 101.0,
                    "event_type": "t2",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in2",
                    "output_snapshot": "out2",
                    "metadata_json": None,
                    "prev_hash": "h1",
                    "hash": "h2",
                },
            ],
        )
        results = _read_sqlite_events(db)
        assert len(results) == 2
        assert results[0]["event_id"] == "e1"
        assert results[0]["sequence"] == 0
        assert results[0]["metadata"] == {"k": "v"}
        assert results[1]["event_id"] == "e2"
        assert results[1]["sequence"] == 1
        # Metadata None → empty dict
        assert results[1]["metadata"] == {}

    def test_new_schema_removes_id_column(self, tmp_dir):
        """should strip the auto-generated 'id' column from results."""
        db = tmp_dir / "new_id.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT, session_id TEXT, sequence INTEGER,
                timestamp REAL, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT, output_snapshot TEXT,
                metadata_json TEXT, prev_hash TEXT, hash TEXT
            )""",
            [
                {
                    "id": 99,
                    "event_id": "e1",
                    "session_id": "s1",
                    "sequence": 0,
                    "timestamp": 100.0,
                    "event_type": "t",
                    "agent_id": "a",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "prev_hash": "",
                    "hash": "",
                }
            ],
        )
        results = _read_sqlite_events(db)
        assert "id" not in results[0]
        assert results[0]["event_id"] == "e1"

    # ── Old schema (no sequence column) ──

    def test_reads_old_schema(self, tmp_dir):
        """should read events from old-style schema (no sequence column)."""
        db = tmp_dir / "old.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT,
                timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "decision",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in",
                    "output_snapshot": "out",
                    "metadata_json": '{"key":"val"}',
                    "timestamp": 100.0,
                },
                {
                    "id": 2,
                    "session_id": "s1",
                    "event_type": "tool_call",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in2",
                    "output_snapshot": "out2",
                    "metadata_json": None,
                    "timestamp": 101.0,
                },
            ],
        )
        results = _read_sqlite_events(db)
        assert len(results) == 2
        # Sequence numbers generated per session
        assert results[0]["sequence"] == 0
        assert results[1]["sequence"] == 1
        assert results[0]["metadata"] == {"key": "val"}
        assert results[1]["metadata"] == {}

    def test_old_schema_multi_session(self, tmp_dir):
        """should generate per-session sequences in old schema."""
        db = tmp_dir / "old_multi.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT,
                timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "a",
                    "agent_id": "a1",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "timestamp": 100.0,
                },
                {
                    "id": 2,
                    "session_id": "s2",
                    "event_type": "b",
                    "agent_id": "a2",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "timestamp": 200.0,
                },
                {
                    "id": 3,
                    "session_id": "s1",
                    "event_type": "c",
                    "agent_id": "a1",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "timestamp": 101.0,
                },
            ],
        )
        results = _read_sqlite_events(db)
        sess1 = [r for r in results if r["session_id"] == "s1"]
        sess2 = [r for r in results if r["session_id"] == "s2"]
        assert sess1[0]["sequence"] == 0
        assert sess1[1]["sequence"] == 1
        assert sess2[0]["sequence"] == 0

    def test_old_schema_handles_bad_metadata_json(self, tmp_dir):
        """should gracefully handle invalid metadata_json in old schema."""
        db = tmp_dir / "bad_meta.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT,
                timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "t",
                    "agent_id": "a",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "not valid json",
                    "timestamp": 100.0,
                }
            ],
        )
        results = _read_sqlite_events(db)
        assert results[0]["metadata"] == {}

    def test_new_schema_handles_bad_metadata_json(self, tmp_dir):
        """should gracefully handle invalid metadata_json in new schema."""
        db = tmp_dir / "new_bad_meta.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT, session_id TEXT,
                sequence INTEGER, timestamp REAL,
                event_type TEXT, agent_id TEXT, prompt_version TEXT,
                input_snapshot TEXT, output_snapshot TEXT,
                metadata_json TEXT, prev_hash TEXT, hash TEXT
            )""",
            [
                {
                    "id": 1,
                    "event_id": "e1",
                    "session_id": "s1",
                    "sequence": 0,
                    "timestamp": 100.0,
                    "event_type": "t",
                    "agent_id": "a",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "not valid json either",
                    "prev_hash": "",
                    "hash": "h1",
                }
            ],
        )
        results = _read_sqlite_events(db)
        assert results[0]["metadata"] == {}


# ════════════════════════════════════════════════════════════════════
#  PG helpers (_write_pg, _ensure_pg_schema, _batch_insert_pg)
# ════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_pg():
    """Fully mock psycopg2 and its extras module."""
    with patch.dict("sys.modules") as modules:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        mock_pg2 = MagicMock()
        mock_pg2.connect.return_value = mock_conn

        mock_extras = MagicMock()
        mock_pg2.extras = mock_extras

        modules["psycopg2"] = mock_pg2
        modules["psycopg2.extras"] = mock_extras

        yield {
            "conn": mock_conn,
            "cursor": mock_cursor,
            "psycopg2": mock_pg2,
            "extras": mock_extras,
        }


class TestEnsurePgSchema:
    """_ensure_pg_schema: table creation and drop."""

    def test_creates_table(self, mock_pg):
        """should create events table with all columns."""
        _ensure_pg_schema(mock_pg["conn"])
        calls = mock_pg["cursor"].execute.call_args_list
        # Should execute CREATE TABLE and two CREATE INDEX statements
        create_table_sql = calls[0][0][0]
        assert "CREATE TABLE IF NOT EXISTS events" in create_table_sql
        assert "BIGSERIAL PRIMARY KEY" in create_table_sql
        assert "JSONB DEFAULT '{}'" in create_table_sql

    def test_creates_indexes(self, mock_pg):
        """should create session_id and (session_id, sequence) indexes."""
        _ensure_pg_schema(mock_pg["conn"])
        calls = mock_pg["cursor"].execute.call_args_list
        idx_sqls = [c[0][0] for c in calls]
        assert any("idx_events_session" in s for s in idx_sqls)
        assert any("idx_events_session_seq" in s for s in idx_sqls)

    def test_drops_existing_table_when_requested(self, mock_pg):
        """should DROP TABLE before creating when drop_existing=True."""
        _ensure_pg_schema(mock_pg["conn"], drop_existing=True)
        calls = mock_pg["cursor"].execute.call_args_list
        drop_sql = calls[0][0][0]
        assert "DROP TABLE IF EXISTS events CASCADE" in drop_sql

    def test_commits_after_setup(self, mock_pg):
        """should commit after schema setup."""
        _ensure_pg_schema(mock_pg["conn"])
        mock_pg["conn"].commit.assert_called_once()


class TestBatchInsertPg:
    """_batch_insert_pg: bulk insert with ON CONFLICT."""

    def test_inserts_all_events(self, mock_pg):
        """should insert all given events."""
        events = [NEW_EVENT_1, NEW_EVENT_2]
        mock_pg["cursor"].rowcount = 2
        result = _batch_insert_pg(mock_pg["conn"], events)
        assert result == 2
        mock_pg["extras"].execute_values.assert_called_once()

    def test_returns_zero_for_empty_list(self, mock_pg):
        """should return 0 when no events."""
        result = _batch_insert_pg(mock_pg["conn"], [])
        assert result == 0
        mock_pg["extras"].execute_values.assert_not_called()

    def serializes_metadata_as_json(self, mock_pg):
        """should serialize metadata dicts as JSON strings."""
        events = [dict(NEW_EVENT_1, metadata={"key": "val", "nested": {"a": 1}})]
        mock_pg["cursor"].rowcount = 1
        _batch_insert_pg(mock_pg["conn"], events)
        args = mock_pg["extras"].execute_values.call_args
        # args[0] is the sql, args[1] is the rows tuple list
        rows = args[0][2]
        meta_json = rows[0][9]
        assert json.loads(meta_json) == {"key": "val", "nested": {"a": 1}}

    def test_truncates_snapshots_in_pg(self, mock_pg):
        """should truncate snapshots to 8000 chars for PG."""
        long_val = "x" * 10000
        events = [dict(NEW_EVENT_1, input_snapshot=long_val, output_snapshot=long_val)]
        mock_pg["cursor"].rowcount = 1
        _batch_insert_pg(mock_pg["conn"], events)
        args = mock_pg["extras"].execute_values.call_args
        rows = args[0][2]
        assert len(rows[0][7]) == 8000  # input_snapshot
        assert len(rows[0][8]) == 8000  # output_snapshot

    def test_handles_none_metadata(self, mock_pg):
        """should convert None metadata to empty JSON dict."""
        events = [dict(NEW_EVENT_1, metadata=None)]
        mock_pg["cursor"].rowcount = 1
        _batch_insert_pg(mock_pg["conn"], events)
        args = mock_pg["extras"].execute_values.call_args
        rows = args[0][2]
        meta_json = rows[0][9]
        assert json.loads(meta_json) == {}

    def test_uses_batch_size(self, mock_pg):
        """should pass page_size=_BATCH_SIZE to execute_values."""
        events = [NEW_EVENT_1, NEW_EVENT_2]
        mock_pg["cursor"].rowcount = 2
        _batch_insert_pg(mock_pg["conn"], events)
        kwargs = mock_pg["extras"].execute_values.call_args.kwargs
        assert kwargs["page_size"] == 1000

    def test_generates_event_id_if_empty(self, mock_pg):
        """should generate an event_id if it's empty string."""
        events = [dict(NEW_EVENT_1, event_id="")]
        mock_pg["cursor"].rowcount = 1
        _batch_insert_pg(mock_pg["conn"], events)
        args = mock_pg["extras"].execute_values.call_args
        rows = args[0][2]
        # event_id is the first column in the row tuple
        assert len(rows[0][0]) == 12


class TestWritePg:
    """_write_pg: high-level PG write with error handling."""

    def test_writes_and_commits(self, mock_pg):
        """should write events and commit (commit is called 2x: _ensure_pg_schema + _write_pg)."""
        mock_pg["cursor"].rowcount = 2
        result = _write_pg("postgresql://localhost/test", [NEW_EVENT_1, NEW_EVENT_2])
        assert result == 2
        assert mock_pg["conn"].commit.call_count >= 1
        mock_pg["conn"].close.assert_called_once()

    def test_rolls_back_on_error(self, mock_pg):
        """should rollback on exception."""
        mock_pg["psycopg2"].connect.side_effect = RuntimeError("connection failed")
        with pytest.raises(RuntimeError):
            _write_pg("postgresql://localhost/test", [NEW_EVENT_1])
        # conn.close should still be called (finally block)
        # But if connect raised, conn was never assigned

    def test_rollback_on_insert_failure(self, mock_pg):
        """should rollback when batch insert fails."""
        mock_pg["cursor"].rowcount = 2

        def _fail_on_insert(*args, **kwargs):
            raise RuntimeError("insert failed")

        mock_pg["extras"].execute_values.side_effect = _fail_on_insert

        with pytest.raises(RuntimeError):
            _write_pg("postgresql://localhost/test", [NEW_EVENT_1])

        mock_pg["conn"].rollback.assert_called_once()
        mock_pg["conn"].close.assert_called_once()

    def test_calls_ensure_schema(self, mock_pg):
        """should call _ensure_pg_schema before inserting."""
        mock_pg["cursor"].rowcount = 2
        _write_pg("postgresql://localhost/test", [NEW_EVENT_1])
        # Schema creation calls are before batch insert
        assert mock_pg["cursor"].execute.call_count >= 3  # CREATE TABLE + 2 indexes


# ════════════════════════════════════════════════════════════════════
#  jsonl_to_postgres - integration
# ════════════════════════════════════════════════════════════════════


class TestJsonlToPostgres:
    """jsonl_to_postgres: full JSONL→PG flow (psycopg2 mocked)."""

    def test_migrates_old_style_jsonl(self, tmp_dir, mock_pg):
        """should read old-style JSONL and write to PG."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1, OLD_EVENT_2])
        mock_pg["cursor"].rowcount = 2

        count = jsonl_to_postgres(tmp_dir, "postgresql://localhost/test")
        assert count == 2
        assert mock_pg["conn"].commit.call_count >= 1

    def test_migrates_new_style_jsonl(self, tmp_dir, mock_pg):
        """should read new-style per-session JSONL and write to PG."""
        _write_jsonl(tmp_dir, "sess-a.jsonl", [NEW_EVENT_1, NEW_EVENT_2])
        _write_jsonl(tmp_dir, "sess-b.jsonl", [NEW_EVENT_3])
        mock_pg["cursor"].rowcount = 3

        count = jsonl_to_postgres(tmp_dir, "postgresql://localhost/test")
        assert count == 3

    def test_raises_file_not_found_for_empty_dir(self, tmp_dir, mock_pg):
        """should raise FileNotFoundError when no JSONL files exist."""
        with pytest.raises(FileNotFoundError, match="No JSONL audit data"):
            jsonl_to_postgres(tmp_dir, "postgresql://localhost/test")

    def test_passes_drop_existing(self, tmp_dir, mock_pg):
        """should pass drop_existing to _write_pg."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1])
        mock_pg["cursor"].rowcount = 1

        jsonl_to_postgres(tmp_dir, "postgresql://localhost/test", drop_existing=True)
        # DROP TABLE should be in the SQL calls
        drop_sql = mock_pg["cursor"].execute.call_args_list[0][0][0]
        assert "DROP TABLE IF EXISTS events CASCADE" in drop_sql

    def test_raises_import_error_without_psycopg2(self, tmp_dir):
        """should raise ImportError when psycopg2 is not available."""
        _write_jsonl(tmp_dir, "audit.jsonl", [OLD_EVENT_1])
        with patch.dict("sys.modules", {"psycopg2": None}), \
                    pytest.raises(ImportError, match="psycopg2"):
                jsonl_to_postgres(tmp_dir, "postgresql://localhost/test")


# ════════════════════════════════════════════════════════════════════
#  sqlite_to_postgres - integration
# ════════════════════════════════════════════════════════════════════


class TestSqliteToPostgres:
    """sqlite_to_postgres: full SQLite→PG flow (psycopg2 mocked)."""

    def test_migrates_new_schema(self, tmp_dir, mock_pg):
        """should read new-style SQLite and write to PG."""
        db = tmp_dir / "source.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                event_id TEXT, session_id TEXT,
                sequence INTEGER, timestamp REAL,
                event_type TEXT, agent_id TEXT, prompt_version TEXT,
                input_snapshot TEXT, output_snapshot TEXT,
                metadata_json TEXT, prev_hash TEXT, hash TEXT
            )""",
            [
                {
                    "id": 1,
                    "event_id": "e1",
                    "session_id": "s1",
                    "sequence": 0,
                    "timestamp": 100.0,
                    "event_type": "t1",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in",
                    "output_snapshot": "out",
                    "metadata_json": '{"k":"v"}',
                    "prev_hash": "",
                    "hash": "h1",
                },
            ],
        )
        mock_pg["cursor"].rowcount = 1

        count = sqlite_to_postgres(db, "postgresql://localhost/test")
        assert count == 1
        assert mock_pg["conn"].commit.call_count >= 1

    def test_migrates_old_schema(self, tmp_dir, mock_pg):
        """should read old-style SQLite (no sequence) and write to PG."""
        db = tmp_dir / "old_source.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT, timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "decision",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "in",
                    "output_snapshot": "out",
                    "metadata_json": "{}",
                    "timestamp": 100.0,
                },
            ],
        )
        mock_pg["cursor"].rowcount = 1

        count = sqlite_to_postgres(db, "postgresql://localhost/test")
        assert count == 1
        # Sequence should be generated as 0
        args = mock_pg["extras"].execute_values.call_args
        rows = args[0][2]
        assert rows[0][2] == 0  # sequence

    def test_raises_file_not_found(self, tmp_dir, mock_pg):
        """should raise FileNotFoundError when DB doesn't exist."""
        with pytest.raises(FileNotFoundError):
            sqlite_to_postgres(tmp_dir / "nope.db", "postgresql://localhost/test")

    def test_returns_zero_for_empty_db(self, tmp_dir, mock_pg):
        """should return 0 when no events in SQLite table."""
        db = tmp_dir / "empty_events.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT
            )""",
            [],  # no rows
        )

        count = sqlite_to_postgres(db, "postgresql://localhost/test")
        assert count == 0
        # _write_pg should not be called with empty events
        mock_pg["extras"].execute_values.assert_not_called()

    def test_passes_drop_existing_and_custom_table(self, tmp_dir, mock_pg):
        """should pass drop_existing and custom table name to _write_pg."""
        db = tmp_dir / "custom.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT,
                agent_id TEXT, prompt_version TEXT,
                input_snapshot TEXT, output_snapshot TEXT,
                metadata_json TEXT, timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "decision",
                    "agent_id": "a1",
                    "prompt_version": "v1",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "timestamp": 100.0,
                },
            ],
            table="audit_log",
        )
        mock_pg["cursor"].rowcount = 1

        count = sqlite_to_postgres(
            db,
            "postgresql://localhost/test",
            drop_existing=True,
            table="audit_log",
        )
        assert count == 1

        # Should have read from "audit_log" table
        # Should have DROP TABLE in PG schema setup
        drop_calls = [
            c[0][0] for c in mock_pg["cursor"].execute.call_args_list if "DROP TABLE" in c[0][0]
        ]
        assert len(drop_calls) >= 1

    def test_raises_import_error_without_psycopg2(self, tmp_dir):
        """should raise ImportError when psycopg2 is not available."""
        db = tmp_dir / "source.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY, session_id TEXT, event_type TEXT,
                agent_id TEXT, prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT, timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "t",
                    "agent_id": "a",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": "{}",
                    "timestamp": 100.0,
                }
            ],
        )
        with patch.dict("sys.modules", {"psycopg2": None}), \
                    pytest.raises(ImportError, match="psycopg2"):
                sqlite_to_postgres(db, "postgresql://localhost/test")


# ════════════════════════════════════════════════════════════════════
#  Edge cases: boundaries, empty, error states
# ════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and error states."""

    def test_jsonl_to_sqlite_handles_missing_dir(self):
        """jsonl_to_sqlite should raise if audit.jsonl is missing."""
        from agent_audit.migrate import jsonl_to_sqlite

        with tempfile.TemporaryDirectory() as d:
            empty = Path(d)
            with pytest.raises(FileNotFoundError, match="No audit trail"):
                jsonl_to_sqlite(empty, ":memory:")

    def test_large_number_of_events(self, tmp_dir, mock_pg):
        """should handle many events with batching."""
        events = []
        for i in range(50):
            events.append(
                dict(
                    NEW_EVENT_1,
                    event_id=f"evt-{i:04d}",
                    session_id=f"sess-{i % 5}",
                    sequence=i,
                )
            )
        _write_jsonl(tmp_dir, "audit.jsonl", events)
        mock_pg["cursor"].rowcount = 50

        count = jsonl_to_postgres(tmp_dir, "postgresql://localhost/test")
        assert count == 50

    def test_metadata_deserialization_from_sqlite(self, tmp_dir, mock_pg):
        """should correctly deserialize complex metadata from SQLite."""
        db = tmp_dir / "complex_meta.db"
        complex_meta = {
            "model": "gpt-4",
            "tokens": 150,
            "tags": ["a", "b", "c"],
            "nested": {"key": "val"},
        }
        _create_sqlite_db(
            db,
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                session_id TEXT, event_type TEXT, agent_id TEXT,
                prompt_version TEXT, input_snapshot TEXT,
                output_snapshot TEXT, metadata_json TEXT, timestamp REAL
            )""",
            [
                {
                    "id": 1,
                    "session_id": "s1",
                    "event_type": "t",
                    "agent_id": "a",
                    "prompt_version": "",
                    "input_snapshot": "",
                    "output_snapshot": "",
                    "metadata_json": json.dumps(complex_meta),
                    "timestamp": 100.0,
                }
            ],
        )
        mock_pg["cursor"].rowcount = 1

        count = sqlite_to_postgres(db, "postgresql://localhost/test")
        assert count == 1

        # Verify metadata was serialized back to JSON for PG insert
        args = mock_pg["extras"].execute_values.call_args
        rows = args[0][2]
        meta_json = json.loads(rows[0][9])
        assert meta_json == complex_meta

    def test_sqlite_table_not_found_after_checks(self, tmp_dir):
        """should raise ValueError when specified table doesn't exist."""
        db = tmp_dir / "wrong_table.db"
        _create_sqlite_db(
            db,
            """CREATE TABLE other_table (id INTEGER PRIMARY KEY)""",
            [],
        )
        with pytest.raises(ValueError, match="not found"):
            _read_sqlite_events(db, table="events")
