"""
Session metadata — tracks every audit session's lifecycle.

A *session* is a continuous period of agent activity, typically
mapping 1:1 with a user conversation or batch job.  Each session
owns one independent SHA-256 hash chain.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Session(Base):
    __tablename__ = "sessions"

    # ── Primary key ──────────────────────────────────────────
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Identity ─────────────────────────────────────────────
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)

    # ── Lifecycle ────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default=text("'active'"),
        nullable=False,
    )  # active | completed | failed | archived
    event_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Audit trail metadata ─────────────────────────────────
    last_hash: Mapped[str] = mapped_column(
        String, default="", server_default=text("''"), nullable=False
    )
    # Is this session's full hash chain verified intact?
    chain_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("FALSE"), nullable=False
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'")
    )

    # ── Timestamp tracking ───────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )

    # ── Constraints & indexes ────────────────────────────────
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_sessions_session_id"),
        Index("ix_sessions_agent", "agent_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_started", started_at.desc()),
        Index("ix_sessions_agent_status", "agent_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Session(id={self.id} session_id={self.session_id} "
            f"agent={self.agent_id} status={self.status} "
            f"events={self.event_count})>"
        )
