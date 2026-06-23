"""
SQLAlchemy declarative base and common audit infrastructure.

Provides the shared Base, an AuditMixin for created_at/updated_at
timestamp tracking, and a naming convention for constraints/indexes.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ── Constraint naming convention ──────────────────────────────
# Ensures Alembic autogenerate produces clean, repeatable migration
# scripts — all indexes/constraints get deterministic names.
_convention = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_convention)


# ── Common mixins ─────────────────────────────────────────────


class AuditMixin:
    """Timestamp columns shared by all audit tables."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


class TimestampMixin(AuditMixin):
    """Timestamp columns with updated_at for mutable rows."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
