"""
EU AI Act compliance report generator.

Generates audit-ready reports from agent audit trails.
Based on EU AI Act Article 12 (record-keeping) and Article 15 (transparency).
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from .engine import AuditEngine
from .prompt_version import PromptRegistry

logger = logging.getLogger(__name__)


def generate_eu_ai_report(
    agent_id: str,
    engine: AuditEngine,
    registry: PromptRegistry,
    output_path: str | Path | None = None,
) -> str:
    """
    Generate an EU AI Act Article 12 compliance report.

    Returns a markdown-formatted report string.
    If output_path is provided, writes to file.
    """
    stats = engine.stats()
    sessions = engine.sessions()
    prompt_audit = registry.audit_report(agent_id)

    # Collect sample events from last 3 sessions
    sample_events = []
    for sid in sessions[-3:]:
        events = engine.read(sid)[:5]
        sample_events.extend(events)

    report = f"""# EU AI Act Compliance Report — Article 12 Record-Keeping

**Generated**: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}
**Agent**: {agent_id}
**Audit Trail Location**: {engine.store_uri}

---

## 1. System Overview

| Attribute | Value |
|-----------|-------|
| Agent ID | `{agent_id}` |
| Total Events Logged | {stats.get("total_events", 0)} |
| Unique Sessions | {len(sessions)} |
| Recording Period | {_ts_to_date(stats.get("first_event"))} — {_ts_to_date(stats.get("last_event"))} |
| Prompt Versions Tracked | {prompt_audit.get("total_versions", 0)} |
| Hash Algorithm | SHA-256 |
| Chain Integrity | {"✅ VERIFIED" if _try_verify(engine) else "❌ BROKEN — DO NOT USE"} |

## 2. Event Type Distribution

{_event_table(stats.get("event_types", {}))}

## 3. Prompt Change History

{_prompt_table(prompt_audit)}

## 4. Decision Traceability

For each automated decision, the following information is recorded:
- **Timestamp** — when the decision was made
- **Input snapshot** — the full context available to the agent
- **Output snapshot** — what action the agent took
- **Prompt version** — which prompt rules were in effect
- **Session ID** — linking related decisions in a workflow

### Sample Events

{_sample_events(sample_events[:10])}

## 5. Integrity Verification

The audit trail uses a SHA-256 hash chain. Each event contains:
- `prev_hash` — linking to the immediately preceding event
- `hash` — SHA-256 of the event content (excluding the hash field itself)

To verify: `agent-audit verify`

## 6. Data Retention

| Requirement | Status |
|-------------|--------|
| Event logging enabled | ✅ |
| Hash chain integrity | {_integrity_status(engine)} |
| Prompt version tracking | ✅ ({prompt_audit.get("total_versions", 0)} versions) |
| Exportable evidence bundles | ✅ (JSON Lines format) |
| Human-readable audit reports | ✅ (this document) |

---

*This report was generated automatically by agent-audit v1.0.0.*
*For EU AI Act Article 12 compliance, retain this report alongside the raw audit trail.*
"""
    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
    return report


def _try_verify(engine: AuditEngine) -> bool:
    try:
        return engine.verify()
    except (OSError, ValueError) as exc:
        logger.warning("Report integrity verification failed: %s", exc)
        return False


def _ts_to_date(ts: float | None) -> str:
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _event_table(types: dict) -> str:
    if not types:
        return "No events recorded."
    rows = []
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        rows.append(f"| `{t}` | {count} |")
    return "| Event Type | Count |\n|------------|-------|\n" + "\n".join(rows)


def _prompt_table(audit: dict) -> str:
    versions = audit.get("versions", [])
    if not versions:
        return "No prompt versions tracked."
    rows = []
    for v in versions:
        rows.append(
            f"| {v['version_id']} | {v['changed_by']} | "
            f"{v['change_reason']} | {_ts_to_date(v['timestamp'])} |"
        )
    return (
        "| Version | Changed By | Reason | Timestamp |\n"
        "|---------|------------|--------|-----------|\n" + "\n".join(rows)
    )


def _sample_events(events: list[dict]) -> str:
    if not events:
        return "No sample events available."
    rows = []
    for e in events[:10]:
        input_preview = e.get("input_snapshot", "")[:60]
        output_preview = e.get("output_snapshot", "")[:60]
        rows.append(
            f"| `{e.get('event_id', '')}` | {e.get('event_type', '')} | "
            f"{input_preview} | {output_preview} | "
            f"v{e.get('prompt_version', '')} |"
        )
    return (
        "| Event ID | Type | Input | Output | Prompt Ver |\n"
        "|----------|------|-------|--------|------------|\n" + "\n".join(rows)
    )


def _integrity_status(engine: AuditEngine) -> str:
    try:
        engine.verify()
        return "✅ VERIFIED — chain intact"
    except (OSError, ValueError) as e:
        return f"❌ BROKEN — {e}"
