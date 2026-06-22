"""
Prompt version tracking for AI agents.

Every prompt change is recorded with:
  - Who changed it
  - When
  - The diff from the previous version
  - Which agent sessions used which version

This enables audit-grade traceability: "Which decisions were made under which prompt?"
"""

import difflib
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PromptVersion:
    """One version of an agent's prompt."""

    version_id: str  # e.g. "v1", "v2", "v3"
    agent_id: str  # Which agent this prompt belongs to
    prompt_text: str  # The full prompt
    changed_by: str  # Who made the change
    change_reason: str  # Why was it changed
    timestamp: float = field(default_factory=time.time)
    prev_version_id: str = ""  # Link to previous version
    hash: str = ""  # SHA-256 of prompt_text


class PromptRegistry:
    """
    Git-like version control for agent prompts.

    Usage:
        registry = PromptRegistry("./logs/my-agent")
        registry.save(
            agent_id="refund-agent",
            prompt_text="You are a refund processing agent...",
            changed_by="alice",
            change_reason="Added $500 limit rule",
        )
        # See what changed
        diff = registry.diff("v1", "v2")
    """

    def __init__(self, log_dir: str | Path):
        self.registry_dir = Path(log_dir) / "prompts"
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.registry_dir / "versions.jsonl"
        self._cache: dict[str, PromptVersion] = {}
        self._load_cache()

    # ═══════════════════════════════ PUBLIC API ═══════════════════════════════

    def save(
        self,
        agent_id: str,
        prompt_text: str,
        changed_by: str,
        change_reason: str,
    ) -> PromptVersion:
        """Save a new prompt version. Returns the created version."""
        prev = self.latest(agent_id)
        version_num = (int(prev.version_id.lstrip("v")) + 1) if prev else 1
        version_id = f"v{version_num}"

        pv = PromptVersion(
            version_id=version_id,
            agent_id=agent_id,
            prompt_text=prompt_text,
            changed_by=changed_by,
            change_reason=change_reason,
            prev_version_id=prev.version_id if prev else "",
            hash=hashlib.sha256(prompt_text.encode()).hexdigest(),
        )

        with open(self.registry_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(pv), ensure_ascii=False) + "\n")

        self._cache[f"{agent_id}:{version_id}"] = pv
        return pv

    def latest(self, agent_id: str) -> PromptVersion | None:
        """Get the latest prompt version for an agent."""
        versions = self.history(agent_id)
        return versions[-1] if versions else None

    def get(self, agent_id: str, version_id: str) -> PromptVersion | None:
        """Get a specific version by ID."""
        key = f"{agent_id}:{version_id}"
        if key in self._cache:
            return self._cache[key]
        return None

    def history(self, agent_id: str) -> list[PromptVersion]:
        """Get all versions for an agent, oldest first."""
        versions = [v for k, v in self._cache.items() if k.startswith(f"{agent_id}:")]
        versions.sort(key=lambda v: v.timestamp)
        return versions

    def diff(self, agent_id: str, v1: str, v2: str) -> str:
        """Generate a unified diff between two prompt versions."""
        pv1 = self.get(agent_id, v1)
        pv2 = self.get(agent_id, v2)
        if not pv1 or not pv2:
            return f"Version not found: {v1 if not pv1 else ''} {v2 if not pv2 else ''}"

        diff_lines = list(
            difflib.unified_diff(
                pv1.prompt_text.splitlines(keepends=True),
                pv2.prompt_text.splitlines(keepends=True),
                fromfile=f"{agent_id}:{v1}",
                tofile=f"{agent_id}:{v2}",
            )
        )
        return "".join(diff_lines)

    def audit_report(self, agent_id: str) -> dict:
        """Generate a prompt version audit report."""
        versions = self.history(agent_id)
        return {
            "agent_id": agent_id,
            "total_versions": len(versions),
            "versions": [
                {
                    "version_id": v.version_id,
                    "changed_by": v.changed_by,
                    "change_reason": v.change_reason,
                    "timestamp": v.timestamp,
                    "hash": v.hash,
                    "prev_version": v.prev_version_id,
                }
                for v in versions
            ],
        }

    def verify(self) -> bool:
        """Verify all stored prompts haven't been tampered with."""
        for key, pv in self._cache.items():
            computed = hashlib.sha256(pv.prompt_text.encode()).hexdigest()
            if not hmac.compare_digest(computed, pv.hash):
                raise Exception(
                    f"Prompt {key} has been tampered with.\n"
                    f"  Stored hash: {pv.hash[:16]}...\n"
                    f"  Computed:    {computed[:16]}..."
                )
        return True

    # ═══════════════════════════════ INTERNAL ═══════════════════════════════

    def _load_cache(self):
        """Load all versions from disk into memory cache."""
        if not self.registry_file.exists():
            return
        with open(self.registry_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    pv = PromptVersion(**data)
                    key = f"{pv.agent_id}:{pv.version_id}"
                    self._cache[key] = pv
                except (json.JSONDecodeError, TypeError):
                    continue
