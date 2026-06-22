-- ── agent-audit PostgreSQL initialization ──
-- Creates required extensions for optimal operation.
-- Core tables are managed by Alembic migrations (alembic/versions/).

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- Cryptographic functions
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- Query monitoring

-- Set statement-level defaults
ALTER DATABASE agent_audit SET timezone TO 'UTC';
ALTER DATABASE agent_audit SET client_min_messages TO warning;

-- Ensure the audit user has full access
GRANT ALL PRIVILEGES ON DATABASE agent_audit TO audit;
