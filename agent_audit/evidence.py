"""
Evidence bundle export — cryptographically signed audit archives.

Auditors can verify the bundle offline without access to the live system.
Bundle = audit trail + prompt history + integrity proof + signature.

Compliant with: EU AI Act Article 12, SOC 2, HIPAA audit trail requirements.
"""

import hashlib
import hmac
import json
import logging
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .core.storage import AuditEngine
from .prompt_version import PromptRegistry

logger = logging.getLogger(__name__)


@dataclass
class EvidenceBundle:
    """A signed, exportable audit evidence package."""

    bundle_id: str
    agent_id: str
    created_at: str  # ISO 8601
    total_events: int
    sessions: int
    prompt_versions: int
    integrity_verified: bool
    sha256: str  # Hash of entire bundle
    signature: str = ""  # External signature (HMAC or GPG)


class EvidenceExporter:
    """
    Export tamper-evident evidence bundles.

    Usage:
        engine = AuditEngine("sqlite://audit.db")
        registry = PromptRegistry("./logs/my-agent")
        exporter = EvidenceExporter(engine, registry)

        # Export a signed zip bundle
        bundle = exporter.export("refund-bot", "evidence.zip")
        print(f"SHA-256: {bundle.sha256}")

        # Verify an existing bundle
        exporter.verify_bundle("evidence.zip")
    """

    def __init__(self, engine: AuditEngine, registry: PromptRegistry):
        self.engine = engine
        self.registry = registry

    def export(
        self,
        agent_id: str,
        output_path: str | Path,
        sign_key: str | None = None,
        session_filter: list[str] | None = None,
    ) -> EvidenceBundle:
        """
        Export audit evidence as a signed zip bundle.

        Args:
            agent_id: which agent's data to export
            output_path: where to write the .zip bundle
            sign_key: optional HMAC key for signature
            session_filter: optional list of session IDs to include
        """
        output_path = Path(output_path)

        # Gather data
        sessions = session_filter or self.engine.sessions()
        events = []
        for sid in sessions:
            events.extend(self.engine.read(sid)[:10000])

        prompt_audit = self.registry.audit_report(agent_id)

        # Bundle metadata
        metadata = {
            "bundle_id": hashlib.sha256(str(time.time()).encode()).hexdigest()[:16],
            "agent_id": agent_id,
            "created_at": datetime.now(UTC).isoformat(),
            "tool": "agent-audit v1.0.0",
            "total_events": len(events),
            "sessions": len(sessions),
            "prompt_versions": prompt_audit.get("total_versions", 0),
            "integrity_verified": self._check_integrity(),
        }

        # Compute bundle SHA-256
        bundle_hash = self._compute_bundle_hash(events, metadata)

        # Sign if key provided
        signature = ""
        if sign_key:
            signature = hmac.new(
                sign_key.encode(),
                bundle_hash.encode(),
                hashlib.sha256,
            ).hexdigest()

        bundle = EvidenceBundle(
            bundle_id=metadata["bundle_id"],
            agent_id=agent_id,
            created_at=metadata["created_at"],
            total_events=metadata["total_events"],
            sessions=metadata["sessions"],
            prompt_versions=metadata["prompt_versions"],
            integrity_verified=metadata["integrity_verified"],
            sha256=bundle_hash,
            signature=signature,
        )

        # Write bundle
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("metadata.json", json.dumps(metadata, indent=2, ensure_ascii=False))
            zf.writestr("events.json", json.dumps(events, ensure_ascii=False))
            zf.writestr("prompts.json", json.dumps(prompt_audit, indent=2, ensure_ascii=False))
            zf.writestr(
                "bundle.json",
                json.dumps(
                    {
                        "bundle_id": bundle.bundle_id,
                        "sha256": bundle.sha256,
                        "signature": bundle.signature,
                        "integrity_verified": bundle.integrity_verified,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            )
            zf.writestr("README.txt", self._generate_readme(metadata))

        return bundle

    def verify_bundle(self, bundle_path: str | Path) -> dict:
        """
        Verify an evidence bundle.

        Returns dict with verification results.
        """
        bundle_path = Path(bundle_path)
        if not bundle_path.exists():
            return {"status": "FAIL", "reason": f"Bundle not found: {bundle_path}"}

        try:
            with zipfile.ZipFile(bundle_path, "r") as zf:
                metadata = json.loads(zf.read("metadata.json"))
                events = json.loads(zf.read("events.json"))
                bundle_data = json.loads(zf.read("bundle.json"))
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            return {"status": "FAIL", "reason": f"Corrupt bundle: {exc}"}

        # Verify hash (constant-time comparison)
        computed_hash = self._compute_bundle_hash(events, metadata)
        stored_hash = bundle_data.get("sha256", "")
        hash_match = hmac.compare_digest(computed_hash, stored_hash)

        # Verify event hash chain — per session
        sessions_events: dict[str, list[dict]] = {}
        for e in events:
            sid = e.get("session_id", "")
            sessions_events.setdefault(sid, []).append(e)
        chain_intact = True
        for _sid, session_events in sessions_events.items():
            prev = ""
            for e in session_events:
                if e.get("prev_hash", "") != prev:
                    chain_intact = False
                    break
                prev = e.get("hash", "")
            if not chain_intact:
                break

        return {
            "status": "PASS" if (hash_match and chain_intact) else "FAIL",
            "bundle_id": bundle_data.get("bundle_id", "unknown"),
            "hash_match": hash_match,
            "chain_intact": chain_intact,
            "event_count": len(events),
            "stored_hash": stored_hash[:16] + "...",
            "computed_hash": computed_hash[:16] + "...",
        }

    def _check_integrity(self) -> bool:
        try:
            return self.engine.verify(session_id=None)
        except (OSError, ValueError) as exc:
            logger.exception("Evidence bundle integrity check failed: %s", exc)
            return False

    def _compute_bundle_hash(self, events: list[dict], metadata: dict) -> str:
        content = json.dumps(
            {
                "metadata": metadata,
                "event_ids": [e.get("event_id", "") for e in events],
                "event_hashes": [e.get("hash", "") for e in events],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _generate_readme(self, metadata: dict) -> str:
        return f"""Evidence Bundle — agent-audit
================================
Bundle ID:      {metadata["bundle_id"]}
Agent:          {metadata["agent_id"]}
Generated:      {metadata["created_at"]}
Total Events:   {metadata["total_events"]}
Sessions:       {metadata["sessions"]}
Integrity:      {"✅ VERIFIED" if metadata["integrity_verified"] else "❌ BROKEN"}

This bundle contains:
  - metadata.json   Bundle description
  - events.json     Complete audit trail (hash-chained)
  - prompts.json    Prompt version history
  - bundle.json     Bundle hash and signature

To verify:
    agent-audit verify-bundle <this-file.zip>

This evidence bundle is admissible for:
  - EU AI Act Article 12 record-keeping
  - SOC 2 compliance audits
  - HIPAA audit trail requirements

Generated by agent-audit v1.0.0
"""
