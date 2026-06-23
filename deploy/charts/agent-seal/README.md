# agent-seal Helm Chart

> **Tamper-evident audit trail for AI agents — production-grade Kubernetes deployment.**

This Helm chart deploys agent-seal on Kubernetes with PostgreSQL, Redis, NGINX reverse proxy, and optional production features (HPA, PDB, NetworkPolicy, ServiceMonitor).

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │    Ingress (TLS)              │
                    │    cert-manager + Let's       │
                    │    Encrypt                    │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │    NGINX (reverse proxy)     │
                    │    health: /health            │
                    │    api:   /api/* -> API       │
                    │    spa:   /      -> API       │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │    API (FastAPI)             │
                    │    port: 8081                 │
                    │    HPA: 2-10 replicas         │
                    │    PDB: minAvailable=1        │
                    └──┬──────────────┬────────────┘
                       │              │
              ┌────────▼──┐   ┌──────▼─────────┐
              │ PostgreSQL │   │    Redis        │
              │ (internal  │   │  (internal or   │
              │  or ext.)  │   │   external)     │
              └────────────┘   └────────────────┘
```

Network isolation via NetworkPolicy mirrors the docker-compose network model:
- **Frontend**: nginx can reach API only
- **Backend**: API can reach DB + Redis; DB/Redis are unreachable from outside

---

## Prerequisites

- Kubernetes 1.25+
- Helm 3.12+
- **External PostgreSQL** (recommended for production — RDS, Cloud SQL, etc.)
- **External Redis** (recommended for production — ElastiCache, Memorystore, etc.)
- **cert-manager** (for TLS — optional, only if `ingress.tls` is enabled)
- **Prometheus Operator** (optional — for ServiceMonitor)

### Storage

Set a default `StorageClass` in your cluster, or set `global.storageClass` in values.

---

## Quick Start

### 1. Install from local chart

```bash
# Install with internal PostgreSQL + Redis (dev/test only)
helm install agent-seal ./deploy/charts/agent-seal \
  --set config.secretKey=$(openssl rand -hex 32)
```

### 2. Wait for deployment

```bash
kubectl rollout status deployment/agent-seal-api
```

### 3. Verify

```bash
# Port-forward for local access
kubectl port-forward svc/agent-seal-nginx 8080:80

# Health check
curl http://localhost:8080/health
# {"status":"ok","version":"1.0.0"}
```

---

## Installation Options

### Development / Testing

Internal PostgreSQL and Redis — zero external dependencies:

```bash
helm install agent-seal ./deploy/charts/agent-seal \
  --set config.secretKey=$(openssl rand -hex 32) \
  --set postgresql.auth.password=$(openssl rand -base64 24)
```

### Production (External DB + Redis)

Uses managed cloud databases — recommended for production:

```bash
helm install agent-seal ./deploy/charts/agent-seal \
  -f ./deploy/charts/agent-seal/values-prod.yaml \
  --set config.secretKey=$(openssl rand -hex 32) \
  --set config.apiKeys[0]="sk-***" \
  --set externalDb.url="postgresql://audit:***@rds.example.com:5432/agent_seal" \
  --set externalRedis.uri="rediss://elasticache.example.com:6379/0" \
  --set ingress.hosts[0].host="audit.example.com" \
  --set ingress.tls[0].hosts[0]="audit.example.com"
```

---

## Configuration

### Required Values

| Parameter | Description | Example |
|---|---|---|
| `config.secretKey` | Cryptographic secret for session management | `openssl rand -hex 32` |
| `externalDb.url` | PostgreSQL connection string (when `postgresql.enabled=false`) | `postgresql://user:***@host:5432/db` |
| `externalRedis.uri` | Redis connection string (when `redis.enabled=false`) | `rediss://host:6379/0` |
| `config.apiKeys` | API authentication keys (empty = open access) | `["sk-..."]` |

### Key Configuration Sections

#### PostgreSQL

| Parameter | Default | Description |
|---|---|---|
| `postgresql.enabled` | `true` | Deploy internal PostgreSQL (set `false` for external) |
| `postgresql.auth.password` | `""` | **REQUIRED** when `enabled=true` — set via `--set`, never commit |
| `postgresql.persistence.size` | `20Gi` | PVC size for PostgreSQL data |
| `externalDb.url` | `""` | External DB connection string |

#### Redis

| Parameter | Default | Description |
|---|---|---|
| `redis.enabled` | `true` | Deploy internal Redis (set `false` for external) |
| `redis.persistence.size` | `8Gi` | PVC size for Redis data |
| `externalRedis.uri` | `""` | External Redis connection string |

#### API

| Parameter | Default | Description |
|---|---|---|
| `replicaCount` | `1` | Number of API replicas |
| `api.resources.requests.cpu` | `250m` | CPU request |
| `api.resources.requests.memory` | `256Mi` | Memory request |
| `api.resources.limits.cpu` | `1000m` | CPU limit |
| `api.resources.limits.memory` | `512Mi` | Memory limit |

#### Ingress

| Parameter | Default | Description |
|---|---|---|
| `ingress.enabled` | `false` | Enable ingress |
| `ingress.className` | `""` | Ingress class (e.g., `nginx`) |
| `ingress.hosts` | `[agent-seal.local]` | Host rules |
| `ingress.tls` | `[]` | TLS configuration |

#### HPA (HorizontalPodAutoscaler)

| Parameter | Default | Description |
|---|---|---|
| `hpa.enabled` | `false` | Enable HPA |
| `hpa.target` | `api` | Target deployment (`api` or `nginx`) |
| `hpa.minReplicas` | `2` | Minimum replicas |
| `hpa.maxReplicas` | `10` | Maximum replicas |
| `hpa.targetCPUUtilizationPercentage` | `70` | CPU target % |

#### PDB (PodDisruptionBudget)

| Parameter | Default | Description |
|---|---|---|
| `pdb.enabled` | `false` | Enable PDB |
| `pdb.minAvailable` | `1` | Minimum available pods during disruptions |

#### NetworkPolicy

| Parameter | Default | Description |
|---|---|---|
| `networkPolicy.enabled` | `false` | Enable NetworkPolicy (requires a CNI that supports it) |
| `networkPolicy.extraIngressCIDRs` | `[]` | Additional allowed CIDRs (monitoring, VPN) |

#### ServiceMonitor

| Parameter | Default | Description |
|---|---|---|
| `serviceMonitor.enabled` | `false` | Enable Prometheus ServiceMonitor |
| `serviceMonitor.interval` | `30s` | Scrape interval |
| `serviceMonitor.path` | `/metrics` | Metrics endpoint path |

---

## Production Deployment

### Using `values-prod.yaml`

The chart ships with a `values-prod.yaml` override file that layers production settings on top of the default `values.yaml`:

```bash
helm install agent-seal ./deploy/charts/agent-seal \
  -f ./deploy/charts/agent-seal/values-prod.yaml \
  --set config.secretKey=$(openssl rand -hex 32) \
  --set config.apiKeys[0]="sk-$(openssl rand -hex 16)" \
  --set externalDb.url="postgresql://audit:***@host:5432/agent_seal" \
  --set externalRedis.uri="rediss://host:6379/0" \
  --set ingress.hosts[0].host="audit.yourdomain.com" \
  --set 'ingress.tls[0].hosts[0]'="audit.yourdomain.com"
```

**What `values-prod.yaml` enables:**

| Feature | Default | values-prod |
|---|---|---|
| API replicas | 1 | 2 |
| Internal PostgreSQL | Yes | No (external required) |
| Internal Redis | Yes | No (external required) |
| HPA | No | Yes (2-10 replicas, CPU 70%) |
| PDB | No | Yes (minAvailable=1) |
| NetworkPolicy | No | Yes |
| Ingress + TLS | No | Yes (with cert-manager) |
| ServiceMonitor | No | Yes |
| PII Redaction | No | Yes |
| Failure notifications | No | Yes |
| API resources | 250m/256Mi | 500m/512Mi - 2C/1Gi |

### Production Checklist

- [ ] Set `config.secretKey` to a strong 64-char hex key
- [ ] Set at least one `config.apiKeys` value
- [ ] Set `externalDb.url` to a managed PostgreSQL instance
- [ ] Set `externalRedis.uri` to a managed Redis instance
- [ ] Restrict `config.corsOrigins` to your frontend domain
- [ ] Set `ingress.hosts` and `ingress.tls` to your real domain
- [ ] Verify cert-manager is installed and configured
- [ ] Review `networkPolicy.extraIngressCIDRs` for your monitoring stack
- [ ] Set resource limits appropriate for your workload
- [ ] Configure `auditLogs.persistence.size` for your retention requirements

---

## Upgrading

```bash
helm upgrade agent-seal ./deploy/charts/agent-seal \
  -f ./deploy/charts/agent-seal/values-prod.yaml \
  --reuse-values
```

**Rolling updates**: The chart uses `RollingUpdate` with `maxUnavailable: 0`, ensuring zero-downtime upgrades with `replicaCount >= 2`.

---

## Uninstalling

```bash
helm uninstall agent-seal
```

**Note**: PersistentVolumeClaims (PVCs) for PostgreSQL, Redis, and audit logs are **not deleted** by default. Delete them manually if needed:

```bash
kubectl delete pvc -l app.kubernetes.io/instance=agent-seal
```

---

## Troubleshooting

### Pods stuck in Pending

```bash
kubectl describe pod -l app.kubernetes.io/instance=agent-seal
```

Common causes:
- PVC cannot be provisioned — check `storageClass` or set `persistence.enabled=false` for testing
- Insufficient cluster resources — reduce `resources.requests` in values

### PostgreSQL won't start

```bash
kubectl logs statefulset/agent-seal-postgresql
```

Common causes:
- `postgresql.auth.password` is empty — set via `--set postgresql.auth.password=...`
- PVC already exists with wrong credentials — delete PVC and reinstall (dev only)

### API crashes with database errors

```bash
kubectl logs deployment/agent-seal-api
```

Common causes:
- `externalDb.url` is malformed — verify format: `postgresql://user:***@host:port/database`
- Database doesn't exist — create it on your external DB before deploying
- NetworkPolicy blocks egress — verify `networkPolicy.enabled` and the external DB CIDR

### HPA not scaling

```bash
kubectl describe hpa agent-seal-api
```

Common causes:
- Metrics server not installed — `kubectl get apiservice v1beta1.metrics.k8s.io`
- Resource requests not set — verify `api.resources.requests` in values

### TLS certificate not issued

```bash
kubectl describe certificate agent-seal-tls
```

Common causes:
- cert-manager not installed — `kubectl get pods -n cert-manager`
- ClusterIssuer not configured — verify `letsencrypt-prod` exists
- DNS not pointing to ingress — verify your domain resolves to the ingress IP

---

## File Structure

```
deploy/charts/agent-seal/
├── Chart.yaml                      # Chart metadata (v1.0.0)
├── values.yaml                     # Default configuration
├── values-prod.yaml                # Production overrides
├── README.md                       # This file
└── templates/
    ├── _helpers.tpl                # Helper templates
    ├── configmap.yaml              # App config + NGINX conf + DB init
    ├── secret.yaml                 # Sensitive values (DB URL, keys)
    ├── deployment-api.yaml         # API Deployment
    ├── deployment-nginx.yaml       # NGINX Deployment
    ├── deployment-redis.yaml       # Redis Deployment
    ├── statefulset-db.yaml         # PostgreSQL StatefulSet
    ├── service-api.yaml            # API Service
    ├── service-db.yaml             # PostgreSQL Service
    ├── service-redis.yaml          # Redis Service
    ├── service-nginx.yaml          # NGINX Service
    ├── ingress.yaml                # Ingress (optional)
    ├── hpa.yaml                    # HorizontalPodAutoscaler (optional)
    ├── pdb.yaml                    # PodDisruptionBudget (optional)
    ├── network-policy.yaml         # NetworkPolicy (optional)
    ├── serviceaccount.yaml         # ServiceAccount
    ├── servicemonitor.yaml         # Prometheus ServiceMonitor (optional)
    ├── pvc.yaml                    # Audit logs PVC
    ├── pvc-redis.yaml              # Redis PVC
    └── NOTES.txt                   # Post-install notes
```

---

## Migration from Docker Compose

If you're migrating from the docker-compose deployment:

| docker-compose | Helm Chart |
|---|---|
| `POSTGRES_USER/PASSWORD` | `postgresql.auth.username` / `postgresql.auth.password` |
| `POSTGRES_DB` | `postgresql.auth.database` |
| `AGENT_SEAL_DB_URL` | `externalDb.url` (or auto-generated if `postgresql.enabled=true`) |
| `AGENT_SEAL_REDIS_URI` | `externalRedis.uri` (or auto-generated if `redis.enabled=true`) |
| `AGENT_SEAL_SECRET_KEY` | `config.secretKey` |
| `AGENT_SEAL_API_KEYS` | `config.apiKeys` (array) |
| All other `AGENT_SEAL_*` vars | `config.*` (mapped 1:1) |
| `nginx/conf.d/*` | `nginx.conf` (Go-templated) |

See [docs/migration-guide.md](../../docs/migration-guide.md) for the full database migration guide.

---

## Support

- **Issues**: https://github.com/agent-seal/agent-seal/issues
- **Documentation**: [README.md](../../README.md) | [API v1](../../docs/api-v1.md) | [Migration Guide](../../docs/migration-guide.md)
- **Release Notes**: [RELEASE-v1.0.md](../../RELEASE-v1.0.md)
