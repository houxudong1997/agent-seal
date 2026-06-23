"""Tests for agent_seal.engine — unified import module validation.

Verifies all 11 re-exported symbols are importable from the canonical
entry point and that source module interfaces are compatible.

Symbols to verify:
  From .core.storage: AuditEngine, AuditStore, create_store,
                       JSONLStore, SQLiteStore, PostgreSQLStore,
                       PostgreSQLStoreORM
  From .core.crypto:   SignedAuditEngine
  From .core.chain:    ChainEvent, SessionChain
"""

from __future__ import annotations

import inspect
from abc import ABC

import pytest

# ═══════════════════════════════════════════════════════════
# 1. ALL RE-EXPORTED SYMBOLS ARE IMPORTABLE
# ═══════════════════════════════════════════════════════════


class TestReexportedSymbols:
    """Every symbol in engine.py's __all__ must be importable."""

    def test_audit_engine_importable(self):
        from agent_seal.engine import AuditEngine

        assert AuditEngine is not None

    def test_audit_store_importable(self):
        from agent_seal.engine import AuditStore

        assert AuditStore is not None

    def test_create_store_importable(self):
        from agent_seal.engine import create_store

        assert callable(create_store)

    def test_jsonl_store_importable(self):
        from agent_seal.engine import JSONLStore

        assert JSONLStore is not None

    def test_sqlite_store_importable(self):
        from agent_seal.engine import SQLiteStore

        assert SQLiteStore is not None

    def test_postgresql_store_importable(self):
        from agent_seal.engine import PostgreSQLStore

        assert PostgreSQLStore is not None

    def test_postgresql_store_orm_importable(self):
        from agent_seal.engine import PostgreSQLStoreORM

        assert PostgreSQLStoreORM is not None

    def test_signed_audit_engine_importable(self):
        from agent_seal.engine import SignedAuditEngine

        assert SignedAuditEngine is not None

    def test_chain_event_importable(self):
        from agent_seal.engine import ChainEvent

        assert ChainEvent is not None

    def test_session_chain_importable(self):
        from agent_seal.engine import SessionChain

        assert SessionChain is not None


# ═══════════════════════════════════════════════════════════
# 2. RE-EXPORTED == SOURCE (IDENTITY CHECK)
# ═══════════════════════════════════════════════════════════


class TestExportIdentity:
    """Each re-exported symbol is the exact same object from the source module."""

    def test_audit_engine_identity(self):
        from agent_seal.core.storage import AuditEngine as Source
        from agent_seal.engine import AuditEngine as ReExported

        assert ReExported is Source

    def test_audit_store_identity(self):
        from agent_seal.core.storage import AuditStore as Source
        from agent_seal.engine import AuditStore as ReExported

        assert ReExported is Source

    def test_create_store_identity(self):
        from agent_seal.core.storage import create_store as source
        from agent_seal.engine import create_store as re_exported

        assert re_exported is source

    def test_jsonl_store_identity(self):
        from agent_seal.core.storage import JSONLStore as Source
        from agent_seal.engine import JSONLStore as ReExported

        assert ReExported is Source

    def test_sqlite_store_identity(self):
        from agent_seal.core.storage import SQLiteStore as Source
        from agent_seal.engine import SQLiteStore as ReExported

        assert ReExported is Source

    def test_postgresql_store_identity(self):
        from agent_seal.core.storage import PostgreSQLStore as Source
        from agent_seal.engine import PostgreSQLStore as ReExported

        assert ReExported is Source

    def test_postgresql_store_orm_identity(self):
        from agent_seal.core.storage import PostgreSQLStoreORM as Source
        from agent_seal.engine import PostgreSQLStoreORM as ReExported

        assert ReExported is Source

    def test_signed_audit_engine_identity(self):
        from agent_seal.core.crypto import SignedAuditEngine as Source
        from agent_seal.engine import SignedAuditEngine as ReExported

        assert ReExported is Source

    def test_chain_event_identity(self):
        from agent_seal.core.chain import ChainEvent as Source
        from agent_seal.engine import ChainEvent as ReExported

        assert ReExported is Source

    def test_session_chain_identity(self):
        from agent_seal.core.chain import SessionChain as Source
        from agent_seal.engine import SessionChain as ReExported

        assert ReExported is Source


# ═══════════════════════════════════════════════════════════
# 3. ALL SYMBOLS IN __all__ ARE RE-EXPORTED
# ═══════════════════════════════════════════════════════════


class TestAllExports:
    """The __all__ list must be accurate — no missing or extra symbols."""

    def test_all_symbols_match_importable(self):
        from agent_seal import engine

        all_symbols = sorted(engine.__all__)
        assert all_symbols == sorted(
            [
                "AuditEngine",
                "AuditStore",
                "ChainEvent",
                "SessionChain",
                "create_store",
                "JSONLStore",
                "PostgreSQLStore",
                "PostgreSQLStoreORM",
                "SignedAuditEngine",
                "SQLiteStore",
            ]
        )

    def test_every_all_symbol_importable(self):
        from agent_seal import engine

        for name in engine.__all__:
            obj = getattr(engine, name, None)
            assert obj is not None, f"{name} in __all__ but not importable via getattr"


# ═══════════════════════════════════════════════════════════
# 4. AuditStore ABSTRACT INTERFACE COMPATIBILITY
# ═══════════════════════════════════════════════════════════


class TestAuditStoreInterface:
    """AuditStore ABC — all backends must implement the same protocol."""

    def test_audit_store_is_abstract(self):
        from agent_seal.engine import AuditStore

        assert issubclass(AuditStore, ABC)

    def test_audit_store_has_write(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "write")
        assert AuditStore.write.__isabstractmethod__

    def test_audit_store_has_read_session(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "read_session")
        assert AuditStore.read_session.__isabstractmethod__

    def test_audit_store_has_sessions(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "sessions")
        assert AuditStore.sessions.__isabstractmethod__

    def test_audit_store_has_stats(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "stats")
        assert AuditStore.stats.__isabstractmethod__

    def test_audit_store_has_verify_session(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "verify_session")
        assert AuditStore.verify_session.__isabstractmethod__

    def test_audit_store_has_close(self):
        from agent_seal.engine import AuditStore

        assert hasattr(AuditStore, "close")
        assert AuditStore.close.__isabstractmethod__


# ═══════════════════════════════════════════════════════════
# 5. STORE BACKEND SUBTYPE CHECK
# ═══════════════════════════════════════════════════════════


class TestStoreSubtypes:
    """All concrete stores must be subclasses of AuditStore."""

    def test_jsonl_store_is_audit_store(self):
        from agent_seal.engine import AuditStore, JSONLStore

        assert issubclass(JSONLStore, AuditStore)

    def test_sqlite_store_is_audit_store(self):
        from agent_seal.engine import AuditStore, SQLiteStore

        assert issubclass(SQLiteStore, AuditStore)

    def test_postgresql_store_is_audit_store(self):
        from agent_seal.engine import AuditStore, PostgreSQLStore

        assert issubclass(PostgreSQLStore, AuditStore)

    def test_postgresql_store_orm_is_audit_store(self):
        from agent_seal.engine import AuditStore, PostgreSQLStoreORM

        assert issubclass(PostgreSQLStoreORM, AuditStore)


# ═══════════════════════════════════════════════════════════
# 6. create_store() SIGNATURE STABILITY
# ═══════════════════════════════════════════════════════════


class TestCreateStoreSignature:
    """The factory function's signature must match documented usage."""

    def test_create_store_has_uri_param(self):
        from agent_seal.engine import create_store

        sig = inspect.signature(create_store)
        params = list(sig.parameters.keys())
        assert "uri" in params

    def test_create_store_has_optional_backend(self):
        from agent_seal.engine import create_store

        sig = inspect.signature(create_store)
        assert "backend" in sig.parameters
        assert sig.parameters["backend"].default is None

    def test_create_store_returns_audit_store(self):
        import tempfile

        from agent_seal.engine import JSONLStore, SQLiteStore, create_store

        with tempfile.TemporaryDirectory() as d:
            store = create_store(f"jsonl://{d}")
            assert isinstance(store, JSONLStore)
            store.close()

        store = create_store("sqlite://:memory:")
        assert isinstance(store, SQLiteStore)
        store.close()


# ═══════════════════════════════════════════════════════════
# 7. ChainEvent DATAClass INTERFACE
# ═══════════════════════════════════════════════════════════


class TestChainEventInterface:
    """ChainEvent must expose all hash-chain fields."""

    def test_chain_event_is_dataclass(self):
        from agent_seal.engine import ChainEvent

        assert hasattr(ChainEvent, "__dataclass_fields__")

    def test_chain_event_has_all_fields(self):
        from agent_seal.engine import ChainEvent

        fields = set(ChainEvent.__dataclass_fields__.keys())
        expected = {
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
        assert fields == expected

    def test_chain_event_can_be_constructed(self):
        from agent_seal.engine import ChainEvent

        event = ChainEvent(
            event_id="evt-001",
            session_id="sess-1",
            sequence=0,
            timestamp=1000.0,
            event_type="decision",
            agent_id="bot",
            prompt_version="v1",
            input_snapshot="input",
            output_snapshot="output",
        )
        assert event.event_id == "evt-001"
        assert event.session_id == "sess-1"
        assert event.sequence == 0
        assert event.metadata == {}


# ═══════════════════════════════════════════════════════════
# 8. SessionChain INTERFACE
# ═══════════════════════════════════════════════════════════


class TestSessionChainInterface:
    """SessionChain must expose chain management methods."""

    def test_session_chain_append(self):
        from agent_seal.engine import SessionChain

        chain = SessionChain("sess-1")
        event = chain.append("decision", "bot", "v1", "input", "output")
        assert event.session_id == "sess-1"
        assert event.sequence == 0
        assert event.hash != ""

    def test_session_chain_verify_ok(self):
        from agent_seal.engine import SessionChain

        chain = SessionChain("sess-1")
        chain.append("decision", "bot", "v1", "input", "output")
        assert chain.verify() is True

    def test_session_chain_verify_tampered(self):
        from agent_seal.engine import SessionChain

        chain = SessionChain("sess-1")
        chain.append("decision", "bot", "v1", "input", "output")
        chain.events[0].output_snapshot = "TAMPERED"
        with pytest.raises(ValueError, match="tampered"):
            chain.verify()

    def test_session_chain_to_dicts(self):
        from agent_seal.engine import SessionChain

        chain = SessionChain("sess-1")
        chain.append("decision", "bot", "v1", "input", "output")
        data = chain.to_dicts()
        assert len(data) == 1
        assert data[0]["session_id"] == "sess-1"

    def test_session_chain_from_dicts(self):
        from agent_seal.engine import SessionChain

        chain = SessionChain("sess-x")
        chain.append("a", "b", "v1", "in", "out")
        data = chain.to_dicts()
        chain2 = SessionChain.from_dicts("sess-x", data)
        assert chain2.verify()
        assert len(chain2.events) == 1


# ═══════════════════════════════════════════════════════════
# 9. AuditEngine HIGH-LEVEL INTERFACE
# ═══════════════════════════════════════════════════════════


class TestAuditEngineInterface:
    """AuditEngine is the top-level API — must expose log/verify/read/sessions/stats."""

    def test_audit_engine_has_log(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "log")
        assert callable(AuditEngine.log)

    def test_audit_engine_has_verify(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "verify")
        assert callable(AuditEngine.verify)

    def test_audit_engine_has_read(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "read")
        assert callable(AuditEngine.read)

    def test_audit_engine_has_sessions(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "sessions")
        assert callable(AuditEngine.sessions)

    def test_audit_engine_has_stats(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "stats")
        assert callable(AuditEngine.stats)

    def test_audit_engine_has_close(self):
        from agent_seal.engine import AuditEngine

        assert hasattr(AuditEngine, "close")
        assert callable(AuditEngine.close)

    def test_audit_engine_log_returns_chain_event(self):
        from agent_seal.engine import AuditEngine, ChainEvent

        engine = AuditEngine("sqlite://:memory:")
        event = engine.log("sess-1", "decision", "bot", "v1", "input", "output")
        assert isinstance(event, ChainEvent)
        assert event.event_type == "decision"
        engine.close()

    def test_audit_engine_log_and_verify(self):
        from agent_seal.engine import AuditEngine

        engine = AuditEngine("sqlite://:memory:")
        engine.log("sess-1", "decision", "bot", "v1", "in", "out")
        assert engine.verify("sess-1") is True
        engine.close()

    def test_audit_engine_stats(self):
        from agent_seal.engine import AuditEngine

        engine = AuditEngine("sqlite://:memory:")
        engine.log("sess-1", "decision", "bot", "v1", "in", "out")
        engine.log("sess-1", "tool_call", "bot", "v1", "in", "result")
        stats = engine.stats()
        assert stats["total_events"] == 2
        assert stats["event_types"]["decision"] == 1
        engine.close()

    def test_jsonl_backend(self):
        import tempfile

        from agent_seal.engine import AuditEngine

        with tempfile.TemporaryDirectory() as d:
            engine = AuditEngine(f"jsonl://{d}")
            engine.log("s-1", "decision", "bot", "v1", "in", "out")
            assert engine.verify("s-1") is True
            engine.close()


# ═══════════════════════════════════════════════════════════
# 10. SignedAuditEngine INTERFACE
# ═══════════════════════════════════════════════════════════


class TestSignedAuditEngineInterface:
    """SignedAuditEngine wraps AuditEngine with cryptographic signing."""

    def test_signed_engine_importable_and_instantiable(self):
        from agent_seal.engine import SignedAuditEngine

        engine = SignedAuditEngine("sqlite://:memory:")
        assert engine.engine is not None
        assert engine.signer is None  # no private key passed
        engine.engine.close()

    def test_signed_engine_log_returns_tuple(self):
        from agent_seal.engine import SignedAuditEngine

        engine = SignedAuditEngine("sqlite://:memory:")
        result = engine.log("s-1", "decision", "bot", "v1", "in", "out")
        assert isinstance(result, tuple)
        assert len(result) == 2
        engine.engine.close()

    def test_signed_engine_has_verify(self):
        from agent_seal.engine import SignedAuditEngine

        engine = SignedAuditEngine("sqlite://:memory:")
        _ = engine.log("s-1", "decision", "bot", "v1", "in", "out")
        assert engine.verify("s-1") is True
        engine.engine.close()

    def test_signed_engine_public_key_property(self):
        from agent_seal.engine import SignedAuditEngine

        engine = SignedAuditEngine("sqlite://:memory:")
        assert engine.public_key_pem is None  # no signer
        engine.engine.close()


# ═══════════════════════════════════════════════════════════
# 11. NEGATIVE: NO STALE SYMBOLS IN MODULE
# ═══════════════════════════════════════════════════════════


class TestNoUnexpectedExports:
    """engine.py should only export what's in __all__."""

    def test_no_extra_public_symbols(self):
        from agent_seal import engine

        public_names = {name for name in dir(engine) if not name.startswith("_")}
        # 'annotations' is from `from __future__ import annotations` —
        # an expected side-effect, not a stale export.
        expected = set(engine.__all__) | {"annotations"}
        assert public_names == expected, f"Unexpected public symbols: {public_names - expected}"


# ═══════════════════════════════════════════════════════════
# 12. MODULE DOCSTRING AND COMPAT NOTE
# ═══════════════════════════════════════════════════════════


class TestModuleDocstring:
    """engine.py must carry architecture documentation."""

    def test_module_has_docstring(self):
        import agent_seal.engine as engine

        assert engine.__doc__ is not None
        assert len(engine.__doc__) > 50

    def test_module_mentions_usage_example(self):
        import agent_seal.engine as engine

        assert "AuditEngine" in engine.__doc__
        assert "create_store" in engine.__doc__

    def test_module_has_compat_note(self):
        import agent_seal.engine as engine

        assert "Compat" in engine.__doc__ or "compat" in engine.__doc__
