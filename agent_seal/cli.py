"""
agent-seal CLI — tamper-evident audit trail for AI agents.

Commands:
  verify   Check audit trail integrity
  trail    Show recent events
  report   Generate EU AI Act compliance report
  log      Record a test event
  prompt   Manage prompt versions
"""

import json
import sys
from pathlib import Path

from .config import config
from .engine import AuditEngine
from .prompt_version import PromptRegistry
from .report import generate_eu_ai_report


def _trail_dir() -> Path:
    """Resolved audit trail directory from config."""
    return config.audit_dir


def cmd_verify():
    """Verify audit trail integrity."""
    engine = AuditEngine()
    print("Verifying audit trail integrity...")
    try:
        engine.verify()
        print("✅ Audit trail is intact. No tampering detected.")
    except ValueError as e:
        print(f"❌ INTEGRITY FAILURE:\n{e}")
        sys.exit(1)


def cmd_trail():
    """Show recent events."""
    engine = AuditEngine()
    stats = engine.stats()

    print(f"Audit Trail: {engine.store_uri}")
    print(f"  Total events: {stats['total_events']}")
    print(f"  Sessions:     {stats['sessions']}")
    print(f"  Event types:  {stats['event_types']}")
    print()

    sessions = engine.sessions()
    if sessions:
        print("Last 3 sessions:")
        for sid in sessions[-3:]:
            events = engine.read(sid)[-3:]
            print(f"\n  Session: {sid}")
            for e in events:
                print(
                    f"    [{e.get('event_type')}] {e.get('event_id')} "
                    f"→ {e.get('output_snapshot', '')[:80]}"
                )


def cmd_report():
    """Generate EU AI Act compliance report."""
    agent_id = sys.argv[3] if len(sys.argv) > 3 else "default-agent"
    engine = AuditEngine()
    registry = PromptRegistry(_trail_dir())

    output = sys.argv[4] if len(sys.argv) > 4 else None
    report = generate_eu_ai_report(agent_id, engine, registry, output)
    print(report)


def cmd_log():
    """Record a test event."""
    if len(sys.argv) < 4:
        print("Usage: agent-seal log <event_type> <output>")
        sys.exit(1)

    event_type = sys.argv[3]
    output_snapshot = sys.argv[4] if len(sys.argv) > 4 else "test output"

    engine = AuditEngine()
    event = engine.log(
        session_id="test-session",
        event_type=event_type,
        agent_id="test-agent",
        prompt_version="v1",
        input_text="CLI manual entry",
        output_text=output_snapshot,
    )
    print(f"✅ Event recorded: {event.event_id}")
    print(f"   Hash: {event.hash[:16]}...")


def cmd_prompt():
    """Manage prompt versions."""
    if len(sys.argv) < 4:
        print("Usage: agent-seal prompt <save|history|diff> ...")
        sys.exit(1)

    sub = sys.argv[3]
    registry = PromptRegistry(_trail_dir())

    if sub == "save":
        if len(sys.argv) < 7:
            print("Usage: agent-seal prompt save <agent_id> <changed_by> <reason>")
            print("  (reads prompt text from stdin)")
            sys.exit(1)
        agent_id = sys.argv[4]
        changed_by = sys.argv[5]
        reason = sys.argv[6]
        print("Paste prompt text (Ctrl+D to finish):")
        text = sys.stdin.read().strip()
        pv = registry.save(agent_id, text, changed_by, reason)
        print(f"✅ Prompt saved: {agent_id}:{pv.version_id} (hash: {pv.hash[:16]}...)")

    elif sub == "history":
        agent_id = sys.argv[4] if len(sys.argv) > 4 else "default-agent"
        versions = registry.history(agent_id)
        for v in versions:
            print(f"  {v.version_id} by {v.changed_by} — {v.change_reason} ({v.timestamp})")

    elif sub == "diff":
        if len(sys.argv) < 7:
            print("Usage: agent-seal prompt diff <agent_id> <v1> <v2>")
            sys.exit(1)
        agent_id = sys.argv[4]
        diff = registry.diff(agent_id, sys.argv[5], sys.argv[6])
        print(diff if diff else "(no differences or versions not found)")

    elif sub == "audit":
        agent_id = sys.argv[4] if len(sys.argv) > 4 else "default-agent"
        report = registry.audit_report(agent_id)
        print(json.dumps(report, indent=2, ensure_ascii=False))


def cmd_serve():
    """Start the API + Dashboard server (FastAPI + uvicorn)."""
    import uvicorn

    from .config import config

    port = int(sys.argv[3]) if len(sys.argv) > 3 else config.api_port
    host = config.api_host
    print(f"agent-seal Dashboard → http://{host}:{port}")
    print(f"  API docs → http://{host}:{port}/docs")
    print(f"  SSE stream → http://{host}:{port}/api/v1/events/stream")
    uvicorn.run(
        "agent_seal.server.app:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
    )


def cmd_benchmark():
    """Run performance benchmark."""
    import os
    import subprocess

    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "benchmark.py")
    example_path = os.path.abspath(example_path)
    if not os.path.exists(example_path):
        print(f"Error: benchmark not found at {example_path}")
        print("Reinstall the package or run from the source tree.")
        sys.exit(1)
    subprocess.run([sys.executable, example_path])


def cmd_demo():
    """Run 60-second demo."""
    import os
    import subprocess

    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "demo.py")
    example_path = os.path.abspath(example_path)
    if not os.path.exists(example_path):
        print(f"Error: demo not found at {example_path}")
        print("Reinstall the package or run from the source tree.")
        sys.exit(1)
    subprocess.run([sys.executable, example_path])


COMMANDS = {
    "verify": cmd_verify,
    "trail": cmd_trail,
    "report": cmd_report,
    "log": cmd_log,
    "prompt": cmd_prompt,
    "serve": cmd_serve,
    "server": cmd_serve,  # backward-compat alias
    "benchmark": cmd_benchmark,
    "demo": cmd_demo,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("agent-seal — tamper-evident audit trail for AI agents")
        print(f"Commands: {', '.join(COMMANDS)}")
        print()
        print("Quick start:")
        print("  agent-seal verify           # Check integrity")
        print("  agent-seal trail            # View recent events")
        print("  agent-seal report <agent>    # EU AI Act compliance report")
        print("  agent-seal log <type> <msg>  # Record a test event")
        print("  agent-seal prompt save ...   # Version control prompts")
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
