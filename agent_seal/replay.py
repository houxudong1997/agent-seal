"""
Deterministic replay for agent decisions.

Replay a past agent session with the same inputs and compare outputs.
If the agent makes a different decision today than it did yesterday
with the same prompt and same inputs → something changed.

This is the core of "can we prove this agent's behavior is consistent?"
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .trail import AuditTrail


@dataclass
class ReplayResult:
    """Result of replaying one agent decision."""

    original_event_id: str
    original_output: str
    replayed_output: str
    match: bool  # exact match?
    drift_score: float  # 0.0 = identical, 1.0 = completely different
    replay_timestamp: float = field(default_factory=time.time)


@dataclass
class ReplayReport:
    """Report from replaying an entire session."""

    session_id: str
    total_events: int
    replayed: int
    matched: int
    drifted: int
    results: list[ReplayResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.replayed == 0:
            return 1.0
        return self.matched / self.replayed

    @property
    def verdict(self) -> str:
        if self.pass_rate >= 0.95:
            return "PASS — Agent behavior is consistent"
        elif self.pass_rate >= 0.80:
            return "WARN — Minor drift detected, investigate"
        else:
            return "FAIL — Significant behavioral change detected"


class AgentReplayer:
    """
    Replay agent decisions from an audit trail.

    Usage:
        trail = AuditTrail("./logs/my-agent")

        def my_agent_fn(input_text: str, prompt: str) -> str:
            # Your actual agent logic
            return agent.run(input_text, system_prompt=prompt)

        replayer = AgentReplayer(trail, my_agent_fn)
        report = replayer.replay_session("sess-001")
        print(f"Pass rate: {report.pass_rate:.0%}")
        print(f"Verdict: {report.verdict}")
    """

    def __init__(
        self,
        trail: AuditTrail,
        agent_fn: Callable[[str, str], str],
        prompt_registry=None,  # Optional PromptRegistry
    ):
        self.trail = trail
        self.agent_fn = agent_fn  # (input_text, prompt) → output_text
        self.prompt_registry = prompt_registry

    def replay_event(self, event: dict) -> ReplayResult:
        """Replay one event and compare with original output."""
        original_output = event.get("output_snapshot", "")
        input_text = event.get("input_snapshot", "")

        # Get the prompt version that was active when this event was recorded
        prompt = self._get_prompt_for_event(event)

        # Replay: run the agent with the same input and prompt
        try:
            replayed_output = self.agent_fn(input_text, prompt)
        except Exception as e:
            replayed_output = f"[REPLAY_ERROR: {e}]"

        # Compute drift score
        match = original_output.strip() == replayed_output.strip()
        drift_score = self._compute_drift(original_output, replayed_output)

        return ReplayResult(
            original_event_id=event.get("event_id", "unknown"),
            original_output=original_output,
            replayed_output=replayed_output,
            match=match,
            drift_score=drift_score,
        )

    def replay_session(self, session_id: str, limit: int = 100) -> ReplayReport:
        """Replay all events in a session and generate a report."""
        events = self.trail.search(session_id=session_id, limit=limit)
        results = [self.replay_event(e) for e in events]

        matched = sum(1 for r in results if r.match)
        drifted = len(results) - matched

        return ReplayReport(
            session_id=session_id,
            total_events=len(events),
            replayed=len(results),
            matched=matched,
            drifted=drifted,
            results=results,
        )

    def replay_all_sessions(self, limit_per_session: int = 50) -> list[ReplayReport]:
        """Replay all sessions in the trail."""
        reports = []
        for sid in self.trail.sessions():
            report = self.replay_session(sid, limit=limit_per_session)
            reports.append(report)
        return reports

    def regression_test(
        self,
        session_ids: list[str] | None = None,
    ) -> tuple[bool, list[ReplayReport]]:
        """
        Run regression test: replay sessions and fail if drift exceeds threshold.

        Returns (passed, reports).
        """
        if session_ids is None:
            session_ids = self.trail.sessions()

        reports = [self.replay_session(sid) for sid in session_ids]
        passed = all(r.pass_rate >= 0.95 for r in reports)
        return passed, reports

    # ═══════════════════════════════ INTERNAL ═══════════════════════════════

    def _get_prompt_for_event(self, event: dict) -> str:
        """Get the prompt text that was active for this event."""
        if self.prompt_registry:
            agent_id = event.get("agent_id", "")
            version_id = event.get("prompt_version", "")
            pv = self.prompt_registry.get(agent_id, version_id)
            if pv is not None:
                return str(pv.prompt_text)

        # Fallback: return empty string (agent should handle gracefully)
        return ""

    def _compute_drift(self, original: str, replayed: str) -> float:
        """Compute a drift score between two outputs. 0=identical, 1=completely different."""
        if original.strip() == replayed.strip():
            return 0.0

        # Simple Jaccard similarity over words
        orig_words = set(original.lower().split())
        replay_words = set(replayed.lower().split())

        if not orig_words and not replay_words:
            return 0.0
        if not orig_words or not replay_words:
            return 1.0

        intersection = orig_words & replay_words
        union = orig_words | replay_words
        jaccard = len(intersection) / len(union)

        return 1.0 - jaccard
