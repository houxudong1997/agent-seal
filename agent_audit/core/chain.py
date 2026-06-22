"""
Hash chain engine — per-session, cryptographically linked audit trails.

Key design decisions:
  - Each session has its OWN hash chain (not one global chain)
  - Chain integrity is O(1) to verify per session
  - Supports concurrent sessions without locking
"""

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChainEvent:
    """One link in a session's hash chain."""

    event_id: str
    session_id: str
    sequence: int  # Position in this session's chain (0,1,2...)
    timestamp: float
    event_type: str
    agent_id: str
    prompt_version: str
    input_snapshot: str
    output_snapshot: str
    metadata: dict = field(default_factory=dict)
    prev_hash: str = ""  # Hash of previous event in THIS session
    hash: str = ""  # SHA-256 of this event


class SessionChain:
    """
    One session's independent hash chain.

    Usage:
        chain = SessionChain(session_id="sess-001")
        chain.append("decision", "bot", "v1", "input", "output")
        chain.verify()  # True if intact
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.events: list[ChainEvent] = []
        self._last_hash = ""

    def append(
        self,
        event_type: str,
        agent_id: str,
        prompt_version: str,
        input_snapshot: str,
        output_snapshot: str,
        metadata: dict | None = None,
    ) -> ChainEvent:
        """Add one event to this session's chain."""
        seq = len(self.events)
        event = ChainEvent(
            event_id=str(uuid.uuid4())[:12],
            session_id=self.session_id,
            sequence=seq,
            timestamp=time.time(),
            event_type=event_type,
            agent_id=agent_id,
            prompt_version=prompt_version,
            input_snapshot=input_snapshot[:8000],
            output_snapshot=output_snapshot[:8000],
            metadata=metadata or {},
            prev_hash=self._last_hash,
        )
        event.hash = self._compute_hash(event)
        self.events.append(event)
        self._last_hash = event.hash
        logger.debug(
            "Chain append: session=%s event=%s seq=%d type=%s hash=%s",
            self.session_id,
            event.event_id,
            seq,
            event_type,
            event.hash[:12],
        )
        return event

    def verify(self) -> bool:
        """Verify this session's chain is intact."""
        prev = ""
        for i, e in enumerate(self.events):
            if e.prev_hash != prev:
                logger.error(
                    "Chain broken at event %d: session=%s expected=%s... got=%s...",
                    i,
                    self.session_id,
                    prev[:16],
                    e.prev_hash[:16],
                )
                raise ValueError(
                    f"Event {i}: chain broken. Expected {prev[:16]}..., got {e.prev_hash[:16]}..."
                )
            # Recompute to verify content hasn't changed
            recomputed = self._compute_hash(e)
            if recomputed != e.hash:
                logger.error(
                    "Content tampered at event %d: session=%s event=%s",
                    i,
                    self.session_id,
                    e.event_id,
                )
                raise ValueError(f"Event {i}: content tampered. Hash mismatch.")
            prev = e.hash
        logger.info(
            "Chain verified: session=%s events=%d",
            self.session_id,
            len(self.events),
        )
        return True

    def to_dicts(self) -> list[dict]:
        """Export as list of dicts for storage."""
        return [
            {
                "event_id": e.event_id,
                "session_id": e.session_id,
                "sequence": e.sequence,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "agent_id": e.agent_id,
                "prompt_version": e.prompt_version,
                "input_snapshot": e.input_snapshot,
                "output_snapshot": e.output_snapshot,
                "metadata": e.metadata,
                "prev_hash": e.prev_hash,
                "hash": e.hash,
            }
            for e in self.events
        ]

    @classmethod
    def from_dicts(cls, session_id: str, data: list[dict]) -> "SessionChain":
        """Restore a chain from stored dicts."""
        chain = cls(session_id)
        # Sort by sequence, defaulting to 0 for items without sequence
        sorted_data = sorted(data, key=lambda x: x.get("sequence", 0))
        for idx, d in enumerate(sorted_data):
            # Keep only valid ChainEvent fields, skip storage-only fields
            valid = {
                k: v
                for k, v in d.items()
                if k
                in {
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
            }
            # Legacy data may lack sequence — fill from sort order
            if "sequence" not in valid or valid["sequence"] is None:
                valid["sequence"] = idx
            chain.events.append(ChainEvent(**valid))
        chain._last_hash = chain.events[-1].hash if chain.events else ""
        logger.debug(
            "Chain restored from dicts: session=%s events=%d",
            session_id,
            len(chain.events),
        )
        return chain

    @staticmethod
    def _compute_hash(event: ChainEvent) -> str:
        raw = (
            f"{event.event_id}|{event.session_id}|{event.sequence}|"
            f"{event.timestamp}|{event.event_type}|{event.agent_id}|"
            f"{event.prompt_version}|{event.input_snapshot}|"
            f"{event.output_snapshot}|{json.dumps(event.metadata, sort_keys=True)}|"
            f"{event.prev_hash}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()
