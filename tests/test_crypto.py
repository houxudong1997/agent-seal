"""Tests for Ed25519 signing."""

import os
import tempfile

from agent_audit.core.crypto import (
    SignedAuditEngine,
    Signer,
    Verifier,
    generate_key_pair,
    load_private_key,
    load_public_key,
    save_private_key,
    save_public_key,
)


def test_generate_and_sign():
    private, public = generate_key_pair()
    signer = Signer(private)
    verifier = Verifier(public)

    sig = signer.sign("hello world")
    assert verifier.verify("hello world", sig)


def test_tampered_data_rejected():
    private, public = generate_key_pair()
    signer = Signer(private)
    verifier = Verifier(public)

    sig = signer.sign("original data")
    assert not verifier.verify("tampered data", sig)


def test_sign_event():
    private, public = generate_key_pair()
    signer = Signer(private)
    verifier = Verifier(public)

    sig = signer.sign_event("abc123", "evt-001", 1234567890.0)
    assert verifier.verify_event("abc123", "evt-001", 1234567890.0, sig)
    # Tampered hash
    assert not verifier.verify_event("xyz999", "evt-001", 1234567890.0, sig)


def test_key_save_load():
    password = b"test-password-123"
    with tempfile.TemporaryDirectory() as d:
        private, public = generate_key_pair()
        save_private_key(private, os.path.join(d, "private.pem"), password)
        save_public_key(public, os.path.join(d, "public.pem"))

        loaded_private = load_private_key(os.path.join(d, "private.pem"), password)
        loaded_public = load_public_key(os.path.join(d, "public.pem"))

        # Re-sign and verify with loaded keys
        sig = Signer(loaded_private).sign("test")
        assert Verifier(loaded_public).verify("test", sig)


def test_signed_audit_engine():
    with tempfile.TemporaryDirectory() as d:
        private, public = generate_key_pair()
        engine = SignedAuditEngine(f"jsonl://{d}", private_key=private)
        event, sig = engine.log("sess-1", "decision", "bot", "v1", "input", "output")

        verifier = Verifier(public)
        assert verifier.verify_event(event.hash, event.event_id, event.timestamp, sig)
        assert engine.public_key_pem is not None


def test_unsigned_engine_works():
    """SignedAuditEngine without a key should still log without signing."""
    with tempfile.TemporaryDirectory() as d:
        engine = SignedAuditEngine(f"jsonl://{d}")
        event, sig = engine.log("sess-1", "decision", "bot", "v1", "in", "out")
        assert sig == ""
        assert event.event_id
