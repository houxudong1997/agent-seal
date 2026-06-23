"""
Hash-chained immutable audit trail for AI agents.

Compatibility wrapper — delegates to agent_seal.engine.AuditEngine.
Kept for backward-compatible imports; new code should use AuditEngine directly.

Usage (compat)::

    trail = AuditTrail("./logs/my-agent")
    trail.log(session_id="sess-001", event_type="tool_call", ...)
    trail.verify()

Preferred new API::

    from agent_seal.engine import AuditEngine
    engine = AuditEngine("jsonl://./logs/my-agent")
    engine.log("sess-001", "tool_call", ...)
"""

import warnings
from dataclasses import dataclass, field

from agent_seal.core.chain import ChainEvent
from agent_seal.engine import AuditEngine


@dataclass
class AuditEvent:
    """One record in the agent's audit trail.

    Compatibility type — wraps ChainEvent without the ``sequence`` field.
    """

    event_id: str
    session_id: str
    timestamp: float  # Unix timestamp
    event_type: str  # tool_call | decision | model_request | guardrail | prompt_change
    agent_id: str  # Which agent
    prompt_version: str  # Prompt version at time of event
    input_snapshot: str  # Full context the agent saw (truncated to N chars)
    output_snapshot: str  # What the agent did/said
    metadata: dict = field(default_factory=dict)
    prev_hash: str = ""  # Hash of the previous event (chain link)
    hash: str = ""  # Hash of this event (computed after creation)

    @classmethod
    def from_chain_event(cls, ce: ChainEvent) -> "AuditEvent":
        """Convert a ChainEvent (engine) to the legacy AuditEvent type."""
        return cls(
            event_id=ce.event_id,
            session_id=ce.session_id,
            timestamp=ce.timestamp,
            event_type=ce.event_type,
            agent_id=ce.agent_id,
            prompt_version=ce.prompt_version,
            input_snapshot=ce.input_snapshot,
            output_snapshot=ce.output_snapshot,
            metadata=ce.metadata,
            prev_hash=ce.prev_hash,
            hash=ce.hash,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEvent":
        """Convert a stored dict to the legacy AuditEvent type."""
        return cls(
            event_id=d.get("event_id", ""),
            session_id=d.get("session_id", ""),
            timestamp=d.get("timestamp", 0.0),
            event_type=d.get("event_type", ""),
            agent_id=d.get("agent_id", ""),
            prompt_version=d.get("prompt_version", ""),
            input_snapshot=d.get("input_snapshot", ""),
            output_snapshot=d.get("output_snapshot", ""),
            metadata=d.get("metadata", {}),
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
        )


class AuditIntegrityError(Exception):
    """Raised when the audit trail integrity check fails."""

    pass


class AuditTrail:
    """
    Immutable hash-chained log for AI agents.

    **Compatibility wrapper** — delegates to ``AuditEngine`` under the hood.
    Prefer ``from agent_seal.engine import AuditEngine`` for new code.

    Usage::

        trail = AuditTrail("./logs/my-agent")
        trail.log(
            session_id="sess-001",
            event_type="tool_call",
            agent_id="refund-agent",
            prompt_version="v3",
            input_snapshot="User: 退款 $45. 订单 #12345",
            output_snapshot="CALL: refund(order_id=12345, amount=45)",
        )
        # Verify integrity at any time
        trail.verify()  # Returns True or raises
    """

    def __init__(self, log_dir: str):
        warnings.warn(
            "AuditTrail is a compatibility wrapper. "
            "Use AuditEngine directly: "
            "from agent_seal.engine import AuditEngine; "
            "engine = AuditEngine(log_dir)",
            DeprecationWarning,
            stacklevel=2,
        )
        self._log_dir = log_dir
        self._engine = AuditEngine(log_dir)

    # ═══════════════════════════════ PUBLIC API ═══════════════════════════════

    def log(
        self,
        session_id: str,
        event_type: str,
        agent_id: str,
        prompt_version: str,
        input_snapshot: str,
        output_snapshot: str,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Record one event to the audit trail. Returns the created event."""
        ce = self._engine.log(
            session_id=session_id,
            event_type=event_type,
            agent_id=agent_id,
            prompt_version=prompt_version,
            input_text=input_snapshot,
            output_text=output_snapshot,
            metadata=metadata,
        )
        return AuditEvent.from_chain_event(ce)

    def verify(self) -> bool:
        """
        Verify the entire audit trail is intact.
        Returns True if no tampering detected.
        Raises AuditIntegrityError if the chain is broken.
        """
        try:
            ok = self._engine.verify(session_id=None)
            return ok
        except ValueError as e:
            raise AuditIntegrityError(str(e)) from e

    def search(
        self,
        session_id: str | None = None,
        event_type: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Search audit events by filter criteria."""
        results: list[dict] = []

        # Collect events from all sessions (or a specific one)
        sids = [session_id] if session_id else self._engine.sessions()

        for sid in sids:
            if len(results) >= limit:
                break
            for event in self._engine.read(sid):
                if event_type and event.get("event_type") != event_type:
                    continue
                if agent_id and event.get("agent_id") != agent_id:
                    continue
                results.append(event)
                if len(results) >= limit:
                    break

        return results

    def sessions(self) -> list[str]:
        """List all unique session IDs in the trail."""
        return self._engine.sessions()

    def stats(self) -> dict:
        """Return summary statistics of the audit trail."""
        return self._engine.stats()
