#!/bin/bash
# ── agent-audit Docker entrypoint ──
# Runs Alembic migrations on every container start (idempotent — safe for
# repeated execution) before launching the application.

set -euo pipefail

echo "=== agent-audit entrypoint ==="
echo "Running database migrations..."

# Run alembic upgrades (safe to run even if already up-to-date)
if [ -f /app/alembic.ini ]; then
    cd /app
    alembic upgrade head
    echo "Migrations complete."
else
    echo "WARNING: alembic.ini not found — skipping migrations."
fi

echo "Starting agent-audit server..."
exec agent-audit serve "$@"
