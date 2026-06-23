#!/usr/bin/env python3
"""
60-second demo of agent-seal capabilities.

Shows: audit logging → integrity verification → tamper detection →
       prompt versioning → policy enforcement → evidence export
"""

import os
import tempfile
from pathlib import Path


def demo():
    # Import here so it works from any directory
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from agent_seal.evidence import EvidenceExporter
    from agent_seal.policy import PolicyEngine, Verdict
    from agent_seal.prompt_version import PromptRegistry
    from agent_seal.trail import AuditIntegrityError, AuditTrail

    from agent_seal.engine import AuditEngine

    # ── Setup ──
    tmp = tempfile.mkdtemp()
    trail = AuditTrail(tmp)
    registry = PromptRegistry(tmp)
    engine = trail._engine  # For evidence exporter (AuditTrail is a compatibility wrapper)
    policy = PolicyEngine()
    print("=" * 55)
    print("  agent-seal — 60-second demo")
    print("=" * 55)

    # ── 1. Log agent activity ──
    print("\n 1. Recording agent decisions...")
    trail.log("sess-001", "request", "refund-bot", "v1", "User: I want a refund for $45", "")
    trail.log(
        "sess-001",
        "decision",
        "refund-bot",
        "v1",
        "Refund $45 for order #12345",
        "Approved: $45 refund — within $100 limit",
    )
    trail.log(
        "sess-001",
        "tool_call",
        "refund-bot",
        "v1",
        "Execute refund",
        "CALL: stripe.refund(ch_789, amount=45)",
    )
    print(f"    ✅ Recorded {trail.stats()['total_events']} events")

    # ── 2. Verify integrity ──
    print("\n 2. Verifying hash chain integrity...")
    trail.verify()
    print("    ✅ Chain intact — no tampering detected")

    # ── 3. Detect tampering ──
    print("\n 3. Testing tamper detection...")
    trail.log("sess-001", "test", "refund-bot", "v1", "test", "original_msg")
    log_file = Path(tmp) / "audit.jsonl"
    lines = log_file.read_text(encoding="utf-8").splitlines()
    tampered = "\n".join(lines[:-1]) + "\n" + lines[-1].replace("original_msg", "CORRUPTED!!")
    log_file.write_text(tampered, encoding="utf-8")
    try:
        trail.verify()
    except AuditIntegrityError:
        print("    ✅ Tampering DETECTED — chain broken at modified event")

    # ── 4. Prompt versioning ──
    print("\n 4. Prompt version tracking...")
    v1 = registry.save(
        "refund-bot", "You process refunds. Auto-approve if < $100.", "alice", "Initial policy"
    )
    v2 = registry.save(
        "refund-bot",
        "You process refunds. Auto-approve if < $500. Require manager for > $500.",
        "alice",
        "Raised auto-approve limit to $500",
    )
    print(f"    ✅ {v1.version_id}: Auto-approve < $100")
    print(f"    ✅ {v2.version_id}: Auto-approve < $500")
    diff = registry.diff("refund-bot", "v1", "v2")
    print(f"    Diff: {len(diff)} chars of changes")

    # ── 5. Policy engine ──
    print("\n 5. Policy engine — blocking dangerous operations...")
    result = policy.evaluate("tool_call", output_snapshot="CALL: shell.run('rm -rf /tmp/*')")
    print(f"    {'❌ BLOCKED' if result.blocked else '✅ ALLOWED'}: {result.reason}")

    result2 = policy.evaluate("decision", output_snapshot="Approved: refund $2,500")
    print(
        f"    {'⚠️ APPROVAL' if result2.verdict == Verdict.APPROVAL else '✅ ALLOWED'}: {result2.reason}"
    )

    # ── 6. Evidence bundle ──
    print("\n 6. Exporting evidence bundle for auditors...")
    exporter = EvidenceExporter(engine, registry)
    bundle_path = os.path.join(tmp, "evidence.zip")
    bundle = exporter.export("refund-bot", bundle_path)
    verify = exporter.verify_bundle(bundle_path)
    print(f"    ✅ Bundle: {bundle.total_events} events, SHA-256: {bundle.sha256[:16]}...")
    print(f"    Verification: {verify['status']}")

    # ── Summary ──
    print("\n" + "=" * 55)
    print("  Demo complete.")
    print(f"   - {trail.stats()['total_events']} events recorded")
    print(f"   - {registry.audit_report('refund-bot')['total_versions']} prompt versions")
    print(f"   - Policy engine: {len(policy.rules)} active rules")
    print(f"   - Evidence bundle: {verify['status']}")
    print("=" * 55)

    # Cleanup
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    demo()
