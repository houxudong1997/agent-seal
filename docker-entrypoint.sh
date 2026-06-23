#!/bin/bash
# ── agent-seal Docker entrypoint ──
# Runs Alembic migrations on every container start (idempotent — safe for
# repeated execution) before launching the application.

set -euo pipefail

echo "=== agent-seal entrypoint ==="
echo "Running database migrations..."

# Run alembic upgrades (safe to run even if already up-to-date)
if [ -f /app/alembic.ini ]; then
    cd /app
    alembic upgrade head
    echo "Migrations complete."
else
    echo "WARNING: alembic.ini not found — skipping migrations."
fi

echo "Starting agent-seal server..."
exec agent-seal serve "$@"
