"""
Prompt change regression testing.

When you change an agent's prompt, this module:
1. Replays historical sessions with the NEW prompt
2. Compares outputs against the ORIGINAL prompt's outputs
3. Reports which sessions would have different outcomes
4. Flags: "The following 7 customer interactions would have gone differently"

This answers: "If we deploy this prompt change, what changes?"
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .prompt_version import PromptRegistry
from .trail import AuditTrail


@dataclass
class RegressionCase:
    """One regression test case — a historical session replayed with a new prompt."""

    event_id: str
    session_id: str
    old_prompt_version: str
    new_prompt_version: str
    input_snapshot: str
    old_output: str
    new_output: str
    changed: bool  # Did the output change?
    change_type: str  # "none" | "minor" | "significant"
    change_summary: str  # Human-readable summary of what changed


@dataclass
class RegressionReport:
    """Full regression test report."""

    agent_id: str
    old_prompt: str  # "v3"
    new_prompt: str  # "v4"
    total_cases: int
    unchanged: int
    minor_changes: int
    significant_changes: int
    cases: list[RegressionCase] = field(default_factory=list)

    @property
    def change_rate(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return (self.minor_changes + self.significant_changes) / self.total_cases

    @property
    def verdict(self) -> str:
        if self.significant_changes == 0:
            return "SAFE — No significant behavioral changes detected"
        elif self.significant_changes <= self.total_cases * 0.05:
            return f"CAUTION — {self.significant_changes} cases changed significantly. Review before deploy."
        else:
            return f"DANGER — {self.significant_changes}/{self.total_cases} cases changed. Do NOT deploy without review."

    def to_markdown(self) -> str:
        """Generate a human-readable markdown report."""
        lines = [
            "# Prompt Regression Test Report",
            "",
            f"**Agent**: `{self.agent_id}`",
            f"**Old Prompt**: `{self.old_prompt}` → **New Prompt**: `{self.new_prompt}`",
            f"**Test Date**: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total cases replayed | {self.total_cases} |",
            f"| Unchanged | {self.unchanged} |",
            f"| Minor changes | {self.minor_changes} |",
            f"| Significant changes | {self.significant_changes} |",
            f"| Change rate | {self.change_rate:.1%} |",
            "",
            f"**Verdict**: {self.verdict}",
            "",
        ]

        if self.significant_changes > 0:
            lines.append("## Significant Changes")
            lines.append("")
            for c in self.cases:
                if c.change_type == "significant":
                    lines.append(f"### Event `{c.event_id}` (Session `{c.session_id}`)")
                    lines.append("")
                    lines.append(f"**Input**: {c.input_snapshot[:200]}")
                    lines.append("")
                    lines.append(f"**Old ({self.old_prompt})**: {c.old_output[:200]}")
                    lines.append("")
                    lines.append(f"**New ({self.new_prompt})**: {c.new_output[:200]}")
                    lines.append("")
                    lines.append(f"**Change**: {c.change_summary}")
                    lines.append("")

        return "\n".join(lines)


class PromptRegressionTester:
    """
    Test what happens when you change a prompt.

    Usage:
        trail = AuditTrail("./logs/my-agent")
        registry = PromptRegistry("./logs/my-agent")

        def my_agent(input_text: str, prompt: str) -> str:
            return actual_agent.run(input_text, system_prompt=prompt)

        tester = PromptRegressionTester(trail, registry, my_agent)

        # What if we deploy v4 instead of v3?
        report = tester.test("refund-bot", old_version="v3", new_version="v4")
        print(report.verdict)
        print(report.to_markdown())
    """

    def __init__(
        self,
        trail: AuditTrail,
        prompt_registry: PromptRegistry,
        agent_fn: Callable[[str, str], str],
    ):
        self.trail = trail
        self.registry = prompt_registry
        self.agent_fn = agent_fn

    def test(
        self,
        agent_id: str,
        old_version: str | None = None,
        new_version: str | None = None,
        session_limit: int = 10,
    ) -> RegressionReport:
        """
        Run regression test comparing old vs new prompt.

        If old_version is None, uses the second-latest version.
        If new_version is None, uses the latest version.
        """
        # Resolve versions
        versions = self.registry.history(agent_id)
        if len(versions) < 2:
            raise ValueError(
                f"Need at least 2 prompt versions for regression testing. "
                f"Found {len(versions)} for {agent_id}."
            )

        old_pv = self.registry.get(agent_id, old_version) if old_version else versions[-2]
        new_pv = self.registry.get(agent_id, new_version) if new_version else versions[-1]

        if not old_pv or not new_pv:
            raise ValueError(f"Version not found: old={old_version}, new={new_version}")

        # Get historical sessions that used the old prompt
        sessions = self.trail.sessions()
        cases = []

        for sid in sessions[:session_limit]:
            events = self.trail.search(
                session_id=sid,
                agent_id=agent_id,
                limit=20,
            )
            for e in events:
                if e.get("prompt_version") != old_pv.version_id:
                    continue

                input_text = e.get("input_snapshot", "")
                old_output = e.get("output_snapshot", "")

                # Replay with new prompt
                try:
                    new_output = self.agent_fn(input_text, new_pv.prompt_text)
                except Exception as ex:
                    new_output = f"[ERROR: {ex}]"

                # Classify the change
                change_type, summary = self._classify_change(old_output, new_output)

                cases.append(
                    RegressionCase(
                        event_id=e.get("event_id", ""),
                        session_id=sid,
                        old_prompt_version=old_pv.version_id,
                        new_prompt_version=new_pv.version_id,
                        input_snapshot=input_text,
                        old_output=old_output,
                        new_output=new_output,
                        changed=(change_type != "none"),
                        change_type=change_type,
                        change_summary=summary,
                    )
                )

        unchanged = sum(1 for c in cases if c.change_type == "none")
        minor = sum(1 for c in cases if c.change_type == "minor")
        significant = sum(1 for c in cases if c.change_type == "significant")

        return RegressionReport(
            agent_id=agent_id,
            old_prompt=old_pv.version_id,
            new_prompt=new_pv.version_id,
            total_cases=len(cases),
            unchanged=unchanged,
            minor_changes=minor,
            significant_changes=significant,
            cases=cases,
        )

    # ═══════════════ INTERNAL ═══════════════

    def _classify_change(self, old: str, new: str) -> tuple[str, str]:
        """Classify the type of change between two outputs."""
        if old.strip() == new.strip():
            return "none", "Identical output"

        old_words = set(old.lower().split())
        new_words = set(new.lower().split())
        intersection = old_words & new_words
        union = old_words | new_words

        if not union:
            return "none", "Both empty"

        jaccard = len(intersection) / len(union)

        if jaccard > 0.9:
            return "minor", f"Minor wording difference (similarity: {jaccard:.0%})"
        elif jaccard > 0.5:
            return "minor", f"Moderate change in phrasing (similarity: {jaccard:.0%})"
        else:
            # Check for key semantic differences
            diffs = []
            if "approved" in old.lower() and "denied" in new.lower():
                diffs.append("Decision changed from APPROVED → DENIED")
            if "denied" in old.lower() and "approved" in new.lower():
                diffs.append("Decision changed from DENIED → APPROVED")
            if "$" in old and "$" in new:
                # Try to find amount differences
                import re

                amounts_old = re.findall(r"\$[\d,]+(?:\.\d{2})?", old)
                amounts_new = re.findall(r"\$[\d,]+(?:\.\d{2})?", new)
                if amounts_old and amounts_new and amounts_old != amounts_new:
                    diffs.append(f"Amount changed: {amounts_old} → {amounts_new}")

            summary = (
                "; ".join(diffs) if diffs else f"Major content change (similarity: {jaccard:.0%})"
            )
            return "significant", summary
