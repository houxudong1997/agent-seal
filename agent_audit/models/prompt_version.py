"""
Prompt version tracking — immutable record of every prompt change,
chained with SHA-256 hashes for tamper-evident audit.

Schema per architecture-v1.md §2.3.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    # ── Primary key ──────────────────────────────────────────
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Identity ─────────────────────────────────────────────
    version_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Audit ────────────────────────────────────────────────
    changed_by: Mapped[str] = mapped_column(String, nullable=False)
    change_reason: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )

    # ── Version chain ────────────────────────────────────────
    prev_version_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    hash: Mapped[str] = mapped_column(String, nullable=False)

    # ── Constraints & indexes ────────────────────────────────
    __table_args__ = (
        UniqueConstraint("agent_id", "version_id", name="uq_prompt_versions_agent_version"),
        Index("ix_prompt_versions_agent", "agent_id", timestamp.desc()),
        Index("ix_prompt_versions_ts", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<PromptVersion(id={self.id} agent={self.agent_id} "
            f"version={self.version_id} changed_by={self.changed_by})>"
        )
