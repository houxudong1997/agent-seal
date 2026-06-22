"""
Encrypted audit log storage.

Uses AES-256-GCM (authenticated encryption).
Each event is encrypted with a unique IV.
The encryption key is derived from a master key via PBKDF2.

Compliant with: EU AI Act, SOC 2, HIPAA encryption-at-rest requirements.
"""

import json
import logging
import os
import struct
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


# ═══════════════════════ KEY MANAGEMENT ═══════════════════════


def derive_key(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a 256-bit AES key from a password. Returns (key, salt)."""
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600_000)
    return kdf.derive(password.encode()), salt


def generate_master_key() -> bytes:
    """Generate a random 256-bit master key."""
    return AESGCM.generate_key(bit_length=256)  # type: ignore[no-any-return]


def save_key(key: bytes, path: str | Path):
    Path(path).write_bytes(key)


def load_key(path: str | Path) -> bytes:
    return Path(path).read_bytes()


# ═══════════════════════ ENCRYPTED STORE ═══════════════════════


class EncryptedStore:
    """
    AES-256-GCM encrypted audit log.

    Usage:
        key = generate_master_key()
        store = EncryptedStore("./logs", key)
        store.write({"event": "data"})
        events = store.read_all()
    """

    VERSION = 1
    HEADER = b"AUDIT\x01"  # Magic + version

    def __init__(self, directory: str | Path, key: bytes):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._aes = AESGCM(key)

    def write(self, session_id: str, data: dict) -> None:
        """Encrypt and write one event."""
        nonce = os.urandom(12)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")

        # Additional authenticated data = session_id
        aad = session_id.encode()

        ciphertext = self._aes.encrypt(nonce, plaintext, aad)

        # Format: magic(6) + nonce(12) + len(4) + ciphertext
        record = self.HEADER + nonce + struct.pack("<I", len(ciphertext)) + ciphertext

        fpath = self.dir / f"{session_id}.enc"
        with open(fpath, "ab") as f:
            f.write(record)

    def read(self, session_id: str) -> list[dict]:
        """Decrypt and read all events for a session."""
        fpath = self.dir / f"{session_id}.enc"
        if not fpath.exists():
            return []

        events = []
        raw = fpath.read_bytes()
        offset = 0
        aad = session_id.encode()

        while offset < len(raw):
            # Parse record
            hdr = raw[offset : offset + 6]
            if hdr != self.HEADER:
                raise ValueError(f"Corrupt record at offset {offset}: bad header")

            nonce = raw[offset + 6 : offset + 18]
            ct_len = struct.unpack("<I", raw[offset + 18 : offset + 22])[0]
            ciphertext = raw[offset + 22 : offset + 22 + ct_len]

            try:
                plaintext = self._aes.decrypt(nonce, ciphertext, aad)
                events.append(json.loads(plaintext))
            except (InvalidTag, json.JSONDecodeError) as exc:
                logger.error(
                    "Decryption failed at offset %d (session=%s): %s",
                    offset,
                    session_id,
                    exc,
                )
                raise ValueError(
                    f"Decryption failed at offset {offset} — "
                    f"data may be tampered or key is wrong: {exc}"
                ) from exc

            offset += 22 + ct_len

        return events

    def sessions(self) -> list[str]:
        return sorted([p.stem for p in self.dir.glob("*.enc")])

    def stats(self) -> dict:
        total = 0
        for sid in self.sessions():
            total += len(self.read(sid))
        return {"total_events": total, "sessions": len(self.sessions())}
