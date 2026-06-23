"""
Cryptographic signing and verification using Ed25519.

Each event can be signed with a private key.
Anyone with the public key can verify the signature offline —
no access to the live system needed.

Compliant with:
  - EU AI Act Article 12 (record-keeping)
  - SOC 2 (audit trail integrity)
  - HIPAA (tamper-evident logs)
"""

import base64
import logging
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

logger = logging.getLogger(__name__)


# ═══════════════════════ KEY MANAGEMENT ═══════════════════════


def generate_key_pair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a new Ed25519 key pair."""
    private = Ed25519PrivateKey.generate()
    logger.info("Generated new Ed25519 key pair")
    return private, private.public_key()


def save_private_key(key: Ed25519PrivateKey, path: str | Path, password: bytes):
    """Save private key to file (PEM format, password-protected).

    Args:
        key: Ed25519 private key to save.
        path: Output file path.
        password: Encryption password (must not be empty).

    Raises:
        ValueError: If password is empty.
    """
    if not password:
        raise ValueError("password must not be empty")
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(password),
    )
    Path(path).write_bytes(pem)
    logger.debug("Saved private key to %s", path)


def load_private_key(path: str | Path, password: bytes | None = None) -> Ed25519PrivateKey:
    """Load private key from PEM file.

    Args:
        path: Path to the PEM file.
        password: Decryption password, or None for unencrypted keys.
    """
    pem = Path(path).read_bytes()
    return serialization.load_pem_private_key(pem, password=password)


def save_public_key(key: Ed25519PublicKey, path: str | Path):
    """Save public key to file (PEM format)."""
    pem = key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    Path(path).write_bytes(pem)
    logger.debug("Saved public key to %s", path)


def load_public_key(path: str | Path) -> Ed25519PublicKey:
    """Load public key from PEM file."""
    pem = Path(path).read_bytes()
    return serialization.load_pem_public_key(pem)


# ═══════════════════════ SIGNING ═══════════════════════


class Signer:
    """
    Signs audit events with Ed25519.

    Usage:
        private, public = generate_key_pair()
        signer = Signer(private)

        signature = signer.sign("some event data")
        # Anyone can verify:
        verifier = Verifier(public)
        assert verifier.verify("some event data", signature)
    """

    def __init__(self, private_key: Ed25519PrivateKey):
        self._key = private_key

    @classmethod
    def from_file(cls, path: str | Path, password: bytes | None = None) -> "Signer":
        return cls(load_private_key(path, password=password))

    def sign(self, data: str) -> str:
        """Sign a string and return base64-encoded signature."""
        sig = self._key.sign(data.encode())
        encoded = base64.b64encode(sig).decode()
        logger.debug("Signed data: len=%d sig=%s...", len(data), encoded[:12])
        return encoded

    def sign_event(self, event_hash: str, event_id: str, timestamp: float) -> str:
        """Sign an audit event (hashes its composite key)."""
        payload = f"{event_id}|{event_hash}|{timestamp}"
        return self.sign(payload)

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._key.public_key()


class Verifier:
    """
    Verifies Ed25519 signatures offline.

    Usage:
        verifier = Verifier(public_key)
        assert verifier.verify_event(event_hash, event_id, timestamp, signature)
    """

    def __init__(self, public_key: Ed25519PublicKey):
        self._key = public_key

    @classmethod
    def from_file(cls, path: str | Path) -> "Verifier":
        return cls(load_public_key(path))

    @classmethod
    def from_pem(cls, pem_str: str) -> "Verifier":
        key = serialization.load_pem_public_key(pem_str.encode())
        return cls(key)

    def verify(self, data: str, signature_b64: str) -> bool:
        """Verify a base64-encoded signature."""
        try:
            sig = base64.b64decode(signature_b64)
            self._key.verify(sig, data.encode())
            logger.debug("Signature verified: len=%d", len(data))
            return True
        except InvalidSignature:
            logger.warning(
                "Signature verification FAILED: len=%d sig=%s...",
                len(data),
                signature_b64[:12],
            )
            return False
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid input during signature verification: len=%d error=%s",
                len(data),
                exc,
            )
            return False

    def verify_event(
        self, event_hash: str, event_id: str, timestamp: float, signature_b64: str
    ) -> bool:
        """Verify a signed audit event."""
        payload = f"{event_id}|{event_hash}|{timestamp}"
        return self.verify(payload, signature_b64)


# ═══════════════════════ SIGNED AUDIT ENGINE ═══════════════════════


class SignedAuditEngine:
    """
    AuditEngine wrapper that signs every event.

    Usage:
        private, public = generate_key_pair()
        engine = SignedAuditEngine(store_uri="./logs", private_key=private)

        # Log events (auto-signed)
        event, signature = engine.log("sess-1", "decision", "bot", "v1", "in", "out")

        # Verify offline
        verifier = Verifier(public)
        assert verifier.verify_event(event.hash, event.event_id, event.timestamp, signature)
    """

    def __init__(
        self,
        store_uri: str = "./audit_logs",
        private_key: Ed25519PrivateKey | None = None,
    ):
        from .storage import AuditEngine

        self.engine = AuditEngine(store_uri)
        self.signer = Signer(private_key) if private_key else None

    def log(
        self,
        session_id: str,
        event_type: str,
        agent_id: str,
        prompt_version: str,
        input_text: str,
        output_text: str,
        metadata: dict | None = None,
    ) -> tuple:
        """
        Log and sign an event.
        Returns (ChainEvent, signature_base64).
        """
        event = self.engine.log(
            session_id,
            event_type,
            agent_id,
            prompt_version,
            input_text,
            output_text,
            metadata,
        )
        signature = ""
        if self.signer:
            signature = self.signer.sign_event(event.hash, event.event_id, event.timestamp)
        return event, signature

    def verify(self, session_id: str | None = None) -> bool:
        return self.engine.verify(session_id)

    @property
    def public_key_pem(self) -> str | None:
        if self.signer:
            return str(self.signer.public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode())
        return None
