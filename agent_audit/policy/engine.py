"""
Policy engine — loads rules from YAML, evaluates in priority order.

Users can add custom rules by dropping YAML files in the rules/ directory.
No code changes needed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml


class Verdict(Enum):
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    APPROVAL = "approval"


@dataclass
class Rule:
    name: str
    priority: int
    description: str
    action: str  # "allow" | "deny" | "warn" | "approval"
    condition: dict
    enabled: bool = True
    _call_times: list[float] = field(default_factory=list, init=False, repr=False)

    def evaluate(self, event_type: str, output: str) -> Verdict:
        if not self.enabled:
            return Verdict.ALLOW

        cond = self.condition

        # Filter by event type
        if "event_type" in cond:
            allowed = cond["event_type"]
            if isinstance(allowed, str) and event_type != allowed:
                return Verdict.ALLOW
            if isinstance(allowed, list) and event_type not in allowed:
                return Verdict.ALLOW

        # Pattern match
        pattern = cond.get("pattern")
        if pattern:
            flags = 0
            if cond.get("pattern_flags") == "IGNORECASE":
                flags = re.IGNORECASE
            if re.search(pattern, output, flags):
                # Check threshold if applicable
                threshold = cond.get("threshold")
                if threshold:
                    amounts = re.findall(r"\$[\d,]+(?:\.\d{2})?", output)
                    if not any(
                        float(a.replace("$", "").replace(",", "")) > threshold
                        for a in amounts
                        if a.replace("$", "").replace(",", "").replace(".", "").isdigit()
                    ):
                        return Verdict.ALLOW
                return Verdict(self.action)

        # Rate limit check
        max_pm = cond.get("max_per_minute")
        if max_pm and event_type == "tool_call":
            if not hasattr(self, "_call_times"):
                object.__setattr__(self, "_call_times", [])
            now = time.time()
            self._call_times = [t for t in self._call_times if now - t < 60]
            self._call_times.append(now)
            if len(self._call_times) > max_pm:
                return Verdict.DENY

        return Verdict.ALLOW


@dataclass
class PolicyResult:
    verdict: Verdict
    triggered: list[str] = field(default_factory=list)
    blocked: bool = False
    reason: str = ""

    @property
    def decision(self) -> Verdict:
        """Backward-compat alias for verdict."""
        return self.verdict

    @property
    def triggered_rules(self) -> list[str]:
        """Backward-compat alias for triggered."""
        return self.triggered


class PolicyEngine:
    """
    Policy engine with YAML-configurable rules.

    Usage:
        engine = PolicyEngine()           # Loads default rules
        engine.add_rules("my_rules.yaml") # Add custom rules
        result = engine.evaluate("tool_call", "rm -rf /tmp")
        if result.blocked:
            print(f"Blocked: {result.reason}")
    """

    def __init__(self, rules_dir: str | Path | None = None):
        self.rules: list[Rule] = []
        if rules_dir is None:
            rules_dir = Path(__file__).parent / "rules"
        if Path(rules_dir).exists():
            for f in sorted(Path(rules_dir).glob("*.yaml")):
                self._load_file(f)

    def _load_file(self, path: Path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for r in data.get("rules", []):
            self.rules.append(Rule(**r))
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rules(self, path: str | Path):
        """Load additional rules from a YAML file."""
        self._load_file(Path(path))

    def evaluate(
        self,
        event_type: str,
        output_snapshot: str,
        input_snapshot: str = "",
        session_id: str = "",
        agent_id: str = "",
        prompt_version: str = "",
    ) -> PolicyResult:
        """
        Evaluate an agent action against all policies.

        Args:
            event_type: Type of event (tool_call, decision, request, etc.)
            output_snapshot: The agent's output / action being evaluated.
            input_snapshot: (ignored, backward compat) The agent's input context.
            session_id: (ignored, backward compat) Session identifier.
            agent_id: (ignored, backward compat) Agent identifier.
            prompt_version: (ignored, backward compat) Prompt version.
        """
        triggered = []
        final = Verdict.ALLOW
        for rule in self.rules:
            v = rule.evaluate(event_type, output_snapshot)
            if v == Verdict.DENY:
                triggered.append(rule.name)
                return PolicyResult(Verdict.DENY, triggered, True, f"Blocked by: {rule.name}")
            if v == Verdict.APPROVAL and final != Verdict.DENY:
                triggered.append(rule.name)
                final = Verdict.APPROVAL
            if v == Verdict.WARN and final == Verdict.ALLOW:
                triggered.append(rule.name)
                final = Verdict.WARN

        reason = ""
        if final == Verdict.APPROVAL:
            reason = f"Approval needed — {', '.join(triggered)}"
        elif final == Verdict.WARN:
            reason = f"Warning — {', '.join(triggered)}"
        return PolicyResult(final, triggered, final == Verdict.DENY, reason)
