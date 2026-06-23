# ─────────────────────────────────────────────────────────────
# agent-seal v1.0 — Multi-stage Docker build
# ─────────────────────────────────────────────────────────────
#
# Stages:
#   spa-builder — build Svelte SPA (Node.js)
#   builder     — compile Python dependencies, prepare wheels
#   production  — minimal runtime image (no build tools)
#
# Build:  docker build --target production -t agent-seal-api:1.0 .
# Dev:    docker build --target builder -t agent-seal-dev .

# ═══════════════════ STAGE 0: SPA Builder ═══════════════════
FROM node:20-alpine AS spa-builder

WORKDIR /app/spa

# Install SPA dependencies (cache layer)
COPY spa/package.json spa/package-lock.json ./
RUN npm ci

# Copy SPA source and build
# Output directory: ../agent_seal/server/static (configured in vite.config.ts outDir)
COPY spa/ ./
RUN npm run build

# ═══════════════════ STAGE 1: Builder ═══════════════════════
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools (removed in production image)
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency manifests first (cache layer)
COPY setup.py README.md ./

# Install Python deps into a virtualenv (including PostgreSQL driver)
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir -e ".[all]"

# Copy full source
COPY . .

# Copy built SPA files from spa-builder stage
COPY --from=spa-builder /app/agent_seal/server/static ./agent_seal/server/static

# ═══════════════════ STAGE 2: Production ═════════════════════
FROM python:3.11-slim AS production

LABEL org.opencontainers.image.title="agent-seal"
LABEL org.opencontainers.image.description="Tamper-evident audit trail for AI agents"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.authors="Mr.H"
LABEL org.opencontainers.image.source="https://github.com/agent-seal/agent-seal"

# Install runtime deps only (no build tools)
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r agentseal && useradd -r -g agentseal -d /app agentseal

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY --from=builder /app/agent_seal ./agent_seal
COPY --from=builder /app/setup.py ./

# Copy Alembic migration files (for `alembic upgrade head` at container start)
COPY --from=builder /app/alembic.ini ./alembic.ini
COPY --from=builder /app/alembic ./alembic

# Copy entrypoint script (runs migrations then starts server)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Make venv Python the default
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create volume mount point
RUN mkdir -p /app/audit_logs && chown -R agentseal:agentseal /app

# Switch to non-root user
USER agentseal

EXPOSE 8081
VOLUME ["/app/audit_logs"]

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')"

# Entrypoint runs Alembic migrations then starts the server
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
