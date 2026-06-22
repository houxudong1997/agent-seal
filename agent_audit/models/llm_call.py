"""
LLM call detail table — every provider request/response is recorded
with token counts, latency, and cost.  Linked to the events table
and OpenTelemetry tracing spans.

Schema per architecture-v1.md §2.3.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class LLMCall(Base):
    __tablename__ = "llm_calls"

    # ── Primary key ──────────────────────────────────────────
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # ── Distributed tracing (OpenTelemetry) ──────────────────
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    span_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_span_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))

    # ── Provider & model ─────────────────────────────────────
    provider: Mapped[str] = mapped_column(
        String, nullable=False
    )  # openai|anthropic|deepseek|custom
    model: Mapped[str] = mapped_column(String, nullable=False)  # gpt-4|claude-3|deepseek-v3

    # ── Token usage ──────────────────────────────────────────
    request_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    response_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    # ── Performance ──────────────────────────────────────────
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0, server_default=text("0"))

    # ── Request / response bodies (optional redacted storage) ─
    request_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Audit linkage ────────────────────────────────────────
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    event_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.event_id"), nullable=True
    )

    # ── Timestamp ────────────────────────────────────────────
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )

    # ── Constraint & indexes ─────────────────────────────────
    __table_args__ = (
        UniqueConstraint("span_id", name="uq_llm_calls_span_id"),
        Index("ix_llm_calls_trace", "trace_id"),
        Index("ix_llm_calls_session", "session_id"),
        Index("ix_llm_calls_ts", timestamp.desc()),
        Index("ix_llm_calls_provider_model", "provider", "model"),
        Index("ix_llm_calls_agent", "agent_id", timestamp.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMCall(id={self.id} provider={self.provider} "
            f"model={self.model} tokens={self.total_tokens} "
            f"latency={self.latency_ms}ms cost=${self.cost_usd})>"
        )
