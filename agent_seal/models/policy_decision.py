"""
Policy decision audit — records every policy evaluation verdict
(allow / deny / warn / approval) linked to its parent event.

Schema per architecture-v1.md §2.3.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    # ── Primary key ──────────────────────────────────────────
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Link to parent event ─────────────────────────────────
    event_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.event_id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Decision ─────────────────────────────────────────────
    rule_name: Mapped[str] = mapped_column(String, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)  # allow | deny | warn | approval
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))

    # ── Timestamp ────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )

    # ── Indexes ──────────────────────────────────────────────
    __table_args__ = (
        Index("ix_policy_decisions_event", "event_id"),
        Index("ix_policy_decisions_ts", timestamp.desc()),
        Index("ix_policy_decisions_verdict", "verdict"),
    )

    def __repr__(self) -> str:
        return (
            f"<PolicyDecision(id={self.id} rule={self.rule_name} "
            f"verdict={self.verdict} blocked={self.blocked})>"
        )
