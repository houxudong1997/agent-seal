"""Initial schema: events, sessions, llm_calls, prompt_versions, policy_decisions

Revision ID: 0001
Revises: None
Create Date: 2026-06-21T21:55:00Z

Schema per architecture-v1.md §2.3 — PostgreSQL backend for agent-audit v1.0.
All indexes and constraints match the architecture spec exactly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── events (core audit trail) ────────────────────────────
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column(
            "sequence", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column(
            "prompt_version",
            sa.String(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("input_snapshot", sa.Text(), server_default=sa.text("''")),
        sa.Column("output_snapshot", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "prev_hash",
            sa.String(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "hash",
            sa.String(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("signature", sa.String(), server_default=sa.text("''")),
        sa.Column("sign_key_id", sa.String(), server_default=sa.text("''")),
        sa.Column("trace_id", sa.String(), server_default=sa.text("''")),
        sa.Column("span_id", sa.String(), server_default=sa.text("''")),
        sa.Column("parent_span_id", sa.String(), server_default=sa.text("''")),
        sa.Column(
            "pii_redacted",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
        ),
        sa.Column("source_ip", postgresql.INET()),
        sa.Column("user_agent", sa.String(), server_default=sa.text("''")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_events")),
        sa.UniqueConstraint("event_id", name=op.f("uq_events_event_id")),
        sa.UniqueConstraint(
            "session_id", "sequence", name=op.f("uq_events_session_sequence")
        ),
    )
    op.create_index("ix_events_ts", "events", [sa.text("timestamp DESC")])
    op.create_index("ix_events_session", "events", ["session_id", "sequence"])
    op.create_index(
        "ix_events_agent", "events", ["agent_id", sa.text("timestamp DESC")]
    )
    op.create_index(
        "ix_events_type", "events", ["event_type", sa.text("timestamp DESC")]
    )
    op.create_index("ix_events_trace", "events", ["trace_id"])
    op.create_index(
        "ix_events_metadata",
        "events",
        ["metadata"],
        postgresql_using="GIN",
    )

    # ── sessions ──────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "event_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_hash",
            sa.String(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "chain_verified",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("session_id", name=op.f("uq_sessions_session_id")),
    )
    op.create_index("ix_sessions_agent", "sessions", ["agent_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index(
        "ix_sessions_started", "sessions", [sa.text("started_at DESC")]
    )
    op.create_index(
        "ix_sessions_agent_status", "sessions", ["agent_id", "status"]
    )

    # ── llm_calls ─────────────────────────────────────────────
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("span_id", sa.String(), nullable=False),
        sa.Column(
            "parent_span_id",
            sa.String(),
            server_default=sa.text("''"),
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "request_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "response_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "total_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            server_default=sa.text("0"),
        ),
        sa.Column("request_body", postgresql.JSONB(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "events.event_id",
                name=op.f("fk_llm_calls_event_id_events"),
            ),
            nullable=True,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
        sa.UniqueConstraint("span_id", name=op.f("uq_llm_calls_span_id")),
    )
    op.create_index("ix_llm_calls_trace", "llm_calls", ["trace_id"])
    op.create_index("ix_llm_calls_session", "llm_calls", ["session_id"])
    op.create_index(
        "ix_llm_calls_ts", "llm_calls", [sa.text("timestamp DESC")]
    )
    op.create_index(
        "ix_llm_calls_provider_model", "llm_calls", ["provider", "model"]
    )
    op.create_index(
        "ix_llm_calls_agent",
        "llm_calls",
        ["agent_id", sa.text("timestamp DESC")],
    )

    # ── prompt_versions ───────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column(
            "change_reason",
            sa.String(),
            server_default=sa.text("''"),
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "prev_version_id",
            sa.String(),
            server_default=sa.text("''"),
        ),
        sa.Column("hash", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint(
            "agent_id",
            "version_id",
            name=op.f("uq_prompt_versions_agent_version"),
        ),
    )
    op.create_index(
        "ix_prompt_versions_agent",
        "prompt_versions",
        ["agent_id", sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_prompt_versions_ts",
        "prompt_versions",
        [sa.text("timestamp DESC")],
    )

    # ── policy_decisions ──────────────────────────────────────
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "events.event_id",
                ondelete="CASCADE",
                name=op.f("fk_policy_decisions_event_id_events"),
            ),
            nullable=False,
        ),
        sa.Column("rule_name", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), server_default=sa.text("''")),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_decisions")),
    )
    op.create_index(
        "ix_policy_decisions_event", "policy_decisions", ["event_id"]
    )
    op.create_index(
        "ix_policy_decisions_ts",
        "policy_decisions",
        [sa.text("timestamp DESC")],
    )
    op.create_index(
        "ix_policy_decisions_verdict", "policy_decisions", ["verdict"]
    )


def downgrade() -> None:
    op.drop_table("policy_decisions")
    op.drop_table("prompt_versions")
    op.drop_table("llm_calls")
    op.drop_table("sessions")
    op.drop_table("events")
