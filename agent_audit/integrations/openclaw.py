"""
OpenClaw MCP integration for agent-audit.

Provides an MCP server that any OpenClaw agent can use to log events
and verify audit trail integrity. One-line setup.

Usage in OpenClaw config:
  mcp_servers:
    agent-audit:
      command: python
      args: ["-m", "agent_audit.integrations.openclaw"]
"""

import json
import os
import sys
from typing import Any


# MCP protocol via stdin/stdout
def mcp_server():
    """MCP server for OpenClaw integration."""
    from ..core.storage import AuditEngine

    engine = AuditEngine(os.getenv("AGENT_AUDIT_URI", "./audit_logs"))

    # Available MCP tools
    tools = {
        "audit_log": {
            "description": "Record an agent action in the tamper-evident audit trail",
            "parameters": {
                "session_id": "string — unique session identifier",
                "event_type": "string — decision|tool_call|model_request|error",
                "agent_id": "string — name of the agent",
                "prompt_version": "string — current prompt version",
                "input": "string — what the agent received",
                "output": "string — what the agent produced",
            },
        },
        "audit_verify": {
            "description": "Verify the integrity of the audit trail",
            "parameters": {
                "session_id": "string (optional) — verify specific session, or all if omitted"
            },
        },
        "audit_stats": {"description": "Get audit trail statistics", "parameters": {}},
        "audit_sessions": {"description": "List all recorded sessions", "parameters": {}},
    }

    # MCP main loop
    for line in sys.stdin:
        try:
            msg = json.loads(line.strip())
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        req_id = msg.get("id", 0)

        if method == "tools/list":
            sys.stdout.write(
                json.dumps(
                    {
                        "id": req_id,
                        "result": {"tools": [{"name": k, **v} for k, v in tools.items()]},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()

        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})

            result: Any = {}
            if name == "audit_log":
                event = engine.log(
                    session_id=args.get("session_id", "default"),
                    event_type=args.get("event_type", "unknown"),
                    agent_id=args.get("agent_id", "openclaw-agent"),
                    prompt_version=args.get("prompt_version", "v1"),
                    input_text=args.get("input", ""),
                    output_text=args.get("output", ""),
                )
                result = {"event_id": event.event_id, "hash": event.hash[:16]}

            elif name == "audit_verify":
                sid = args.get("session_id", "")
                ok = engine.verify(sid) if sid else engine.verify()
                result = {"integrity": "ok" if ok else "broken"}

            elif name == "audit_stats":
                result = engine.stats()

            elif name == "audit_sessions":
                result = engine.sessions()

            else:
                result = {"error": f"Unknown tool: {name}"}

            sys.stdout.write(json.dumps({"id": req_id, "result": result}) + "\n")
            sys.stdout.flush()

        elif method == "initialize":
            sys.stdout.write(
                json.dumps({"id": req_id, "result": {"protocol_version": "2024-11-05"}}) + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    mcp_server()
