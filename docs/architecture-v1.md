# agent-audit v1.0 架构升级方案

> **版本**: v0.1 → v1.0 Architecture Design
> **作者**: workstation-planner
> **日期**: 2026-06-21
> **状态**: Draft / Review

---

## 目录

1. [背景与现状分析](#1-背景与现状分析)
2. [规模化存储路线](#2-规模化存储路线)
3. [Station Dashboard 集成方案](#3-station-dashboard-集成方案)
4. [LLM 调用链自动追踪](#4-llm-调用链自动追踪)
5. [企业部署架构](#5-企业部署架构)
6. [产品化路线图](#6-产品化路线图)
7. [方案评估与风险](#7-方案评估与风险)
8. [实施计划](#8-实施计划)

---

## 1. 背景与现状分析

### 1.1 项目定位

agent-audit 是一个面向 AI Agent 的防篡改审计追踪系统。核心价值：

- **SHA-256 哈希链**确保每条记录不可篡改
- **每条事件独立验证**，篡改立即发现
- 支持 **EU AI Act Article 12**（2026年8月生效）合规要求
- 覆盖 **SOC 2 / HIPAA** 审计标准

### 1.2 v0.1.0 现状

```
agent_audit/
├── trail.py            # JSONL AuditTrail — 简单哈希链入口
├── storage.py          # SQLiteTrail — SQLite 备份
├── core/
│   ├── chain.py        # SessionChain — 每个 session 独立哈希链
│   ├── storage.py      # AuditStore ABC + JSONLStore/SQLiteStore + AuditEngine
│   ├── crypto.py       # Ed25519 签名
│   ├── encrypted.py    # AES-256-GCM 加密存储
│   ├── redact.py       # PII 脱敏
│   └── rotation.py     # 日志轮转
├── server/api.py       # REST API (内置 http.server)
├── dashboard.py        # 独立 Dashboard server (内联 HTML)
├── policy/engine.py    # YAML 策略引擎
├── evidence.py         # 证据包导出 (.zip)
├── replay.py / regression.py   # 回放与回归测试
├── integrations.py     # LangChain callback 封装
└── integrations/openclaw.py    # MCP 服务器
```

**现有问题诊断**：

| # | 问题 | 严重性 | 影响 |
|---|------|--------|------|
| 1 | **存储接口碎片化** — `trail.py`(JSONL)、`storage.py`(SQLite)、`core/storage.py`(ABC) 三套接口 | 高 | API 不一致，用户困惑 |
| 2 | **无生产级存储** — JSONL 不适合高并发，SQLite 单机瓶颈 | 高 | 无法支撑企业级部署 |
| 3 | **Dashboard 简陋** — 内联 HTML + 静态刷新 | 中 | 运维/合规均无法满足 |
| 4 | **无 LLM 自动追踪** — 所有 `log()` 调用都是手动 | 高 | 集成成本高，漏记风险 |
| 5 | **无 .env 配置系统** — 所有配置硬编码 | 中 | 部署不灵活 |
| 6 | **Docker 未优化** — 单阶段构建，无 nginx | 低 | 镜像体积大 |
| 7 | **无 K8s 部署方案** | 中 | 企业部署门槛高 |
| 8 | **无结构化日志** | 中 | 排障困难 |

### 1.3 需求目标

1. **生产级存储** — JSONL/SQLite → PostgreSQL（主）+ TimescaleDB（时间序列）
2. **企业级 Dashboard** — 运维视角 + 合规视角双视图
3. **零侵入 LLM 追踪** — 自动捕获 LLM 调用链，替代手动 `trail.log()`
4. **云原生部署** — Docker Compose → K8s Helm Chart
5. **产品化路线** — v0.1 → v1.0 → 商业化

---

## 2. 规模化存储路线

### 2.1 方案对比

| 维度 | 方案 A: PostgreSQL 单库 | 方案 B: PostgreSQL + TimescaleDB | 方案 C: 分层存储 (冷热分离) |
|------|------------------------|----------------------------------|------------------------------|
| **数据模型** | 单表 events，JSONB metadata | events 表 + 自动分区 (按时间) | Hot: PG (近30天), Cold: S3/Loki |
| **查询能力** | SQL 完整 | SQL + 时间窗口 + 连续聚合 | SQL (hot) + API (cold) |
| **写入 TPS** | ~5k/s (单机) | ~50k/s (超表) | ~5k/s + S3 unlimited |
| **存储成本** | 中等 | 中等 (分区自动压缩) | 低 (冷存储便宜 10x) |
| **运维复杂度** | 低 | 中 (多一个扩展) | 高 (数据迁移逻辑) |
| **适合场景** | 中小规模 (<1M events/天) | 大规模 (>1M events/天) | 超大规模 (>10M events/天) |
| **审计合规** | ✅ 满足 | ✅ 满足 | ✅ 满足 (不可变存储) |

### 2.2 推荐方案：方案 B — PostgreSQL + TimescaleDB

**理由**：agent-audit 的核心是**时间序列审计事件**，TimescaleDB 的超表（Hypertable）天然适合按时间分区的审计日志。写入性能满足企业初期需求，且未来可平滑扩展。

**但初始实施采用方案 A**（纯 PostgreSQL），因为：
- 降低初始部署复杂度
- 数据量达到 500 万事件/天后再加 TimescaleDB 是零停机操作
- TimescaleDB 是 PostgreSQL 扩展，从 A 到 B 无需改代码

### 2.3 数据模型设计

```sql
-- ============================================
-- schema: agent_audit (PostgreSQL)
-- ============================================

-- 核心审计事件表
CREATE TABLE events (
    id              BIGSERIAL PRIMARY KEY,
    
    -- 事件标识
    event_id        UUID NOT NULL DEFAULT gen_random_uuid(),
    session_id      TEXT NOT NULL,
    sequence        INT NOT NULL DEFAULT 0,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    -- 审计维度
    event_type      TEXT NOT NULL,        -- decision|tool_call|model_request|guardrail|error
    agent_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL DEFAULT '',
    
    -- 内容
    input_snapshot  TEXT DEFAULT '',
    output_snapshot TEXT DEFAULT '',
    metadata        JSONB DEFAULT '{}',
    
    -- 哈希链
    prev_hash       TEXT NOT NULL DEFAULT '',
    hash            TEXT NOT NULL DEFAULT '',
    
    -- Ed25519 签名 (可选)
    signature       TEXT DEFAULT '',
    sign_key_id     TEXT DEFAULT '',
    
    -- LLM 调用链追踪 (v1.0 新增)
    trace_id        TEXT DEFAULT '',       -- OpenTelemetry trace ID
    span_id         TEXT DEFAULT '',       -- OpenTelemetry span ID
    parent_span_id  TEXT DEFAULT '',
    
    -- 审计元信息
    pii_redacted    BOOLEAN DEFAULT FALSE,
    source_ip       INET,
    user_agent      TEXT DEFAULT '',
    
    -- 约束
    UNIQUE (event_id),
    UNIQUE (session_id, sequence)
);

-- 索引
CREATE INDEX idx_events_ts ON events (timestamp DESC);
CREATE INDEX idx_events_session ON events (session_id, sequence);
CREATE INDEX idx_events_agent ON events (agent_id, timestamp DESC);
CREATE INDEX idx_events_type ON events (event_type, timestamp DESC);
CREATE INDEX idx_events_trace ON events (trace_id);
CREATE INDEX idx_events_metadata ON events USING GIN (metadata);

-- === 转为 TimescaleDB 超表（数据量达到后执行）===
-- SELECT create_hypertable('events', 'timestamp', chunk_time_interval => INTERVAL '1 day');
-- SELECT add_compression_policy('events', INTERVAL '30 days');

-- Prompt 版本表
CREATE TABLE prompt_versions (
    id              BIGSERIAL PRIMARY KEY,
    version_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    prompt_text     TEXT NOT NULL,
    changed_by      TEXT NOT NULL,
    change_reason   TEXT DEFAULT '',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    prev_version_id TEXT DEFAULT '',
    hash            TEXT NOT NULL,
    UNIQUE (agent_id, version_id)
);

-- 策略审计表（每次策略评估的记录）
CREATE TABLE policy_decisions (
    id              BIGSERIAL PRIMARY KEY,
    event_id        UUID REFERENCES events(event_id) ON DELETE CASCADE,
    rule_name       TEXT NOT NULL,
    verdict         TEXT NOT NULL,          -- allow|deny|warn|approval
    blocked         BOOLEAN NOT NULL,
    reason          TEXT DEFAULT '',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_policy_event ON policy_decisions (event_id);
CREATE INDEX idx_policy_ts ON policy_decisions (timestamp DESC);

-- LLM 调用明细表 (v1.0 新增)
CREATE TABLE llm_calls (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        TEXT NOT NULL,          -- 关联 trace
    span_id         TEXT NOT NULL UNIQUE,
    parent_span_id  TEXT DEFAULT '',
    
    -- 调用信息
    provider        TEXT NOT NULL,          -- openai|anthropic|deepseek|custom
    model           TEXT NOT NULL,          -- gpt-4|claude-3|deepseek-v3
    request_tokens  INT DEFAULT 0,
    response_tokens INT DEFAULT 0,
    total_tokens    INT DEFAULT 0,
    latency_ms      INT DEFAULT 0,
    cost_usd        DECIMAL(10,6) DEFAULT 0,
    
    -- 请求/响应 (可选脱敏存储)
    request_body    JSONB,
    response_body   JSONB,
    
    -- 审计关联
    session_id      TEXT,
    agent_id        TEXT,
    event_id        UUID REFERENCES events(event_id),
    
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_llm_trace ON llm_calls (trace_id);
CREATE INDEX idx_llm_session ON llm_calls (session_id);
CREATE INDEX idx_llm_ts ON llm_calls (timestamp DESC);
```

### 2.4 迁移路径

```
阶段 1: JSONL ↔ SQLite (并行)
  ├─ 现有用户继续使用 JSONL/SQLite
  └─ 新增 PostgreSQL backend (AuditStore 接口)

阶段 2: SQLite → PostgreSQL (零停机)
  ├─ 背景运行 pgloader 迁移脚本
  └─ 支持增量同步 (sync_poll)

阶段 3: (可选) TimescaleDB 启用
  └─ create_hypertable + 压缩策略
```

---

## 3. Station Dashboard 集成方案

### 3.1 需求定义

Dashboard 需要两个视角：

**运维视角** (Monitoring):
- 系统实时健康度 (事件吞吐量、延迟、错误率)
- 存储使用量 (PSQL 表大小、磁盘)
- LLM 调用统计 (Token 消耗、成本、延迟 P50/P95/P99)
- 策略命中/阻断统计
- 实时事件流

**合规视角** (Compliance):
- 哈希链完整性状态 (每 session 验证结果)
- 提示词变更历史时间线
- 证据包导出入口
- EU AI Act 合规报告一键生成
- 审计员视图：只读 + 可导出

### 3.2 方案对比

| 维度 | 方案 A: FastAPI + Jinja2 SSR | 方案 B: FastAPI + Vue3 SPA | 方案 C: Grafana 预制面板 |
|------|------------------------------|----------------------------|--------------------------|
| **开发成本** | 低 | 高 | 低 (预置面板) |
| **交互体验** | 一般 | 优秀 | 限制 (只读) |
| **可定制性** | 高 | 高 | 低 (Grafana 原生) |
| **审计合规** | 需自建 | 需自建 | 自带权限+审计 |
| **实时性** | WebSocket 手动实现 | WebSocket 手动实现 | 原生 PromQL 实时 |
| **维护成本** | 中等 | 高 | 低 |
| **推荐度** | ⭐⭐ 过渡方案 | ⭐⭐⭐ 长期方案 | ⭐⭐⭐⭐ 推荐 |

### 3.3 推荐方案：混合架构

**解释**：建议 FastAPI + 预制 Svelte Dashboard（构建产物部署为静态文件）+ Prometheus/Grafana 补充运维面板。

```
┌─────────────────────────────────────────────────────────┐
│                   Station Dashboard                     │
├───────────────────────┬─────────────────────────────────┤
│    运维视图 (Grafana)  │    合规视图 (Svelte App)        │
│                       │                                 │
│  ┌─────────────────┐  │  ┌───────────────────────────┐  │
│  │  Event Throughput│  │  │  链完整性检查              │  │
│  │  Token Usage     │  │  │  提示词版本时间线          │  │
│  │  P99 Latency     │  │  │  证据包导出                │  │
│  │  Storage Usage   │  │  │  合规报告生成              │  │
│  │  Error Rate      │  │  │  事件搜索                  │  │
│  └─────────────────┘  │  └───────────────────────────┘  │
│                       │                                 │
│  Data Source:         │  Data Source:                   │
│  Prometheus           │  REST API (FastAPI)             │
└───────────────────────┴─────────────────────────────────┘
```

### 3.4 Dashboard 功能模块

```yaml
dashboard:
  # ── 运维视图 (Grafana + Prometheus) ──
  ops:
    metrics_endpoint: /metrics          # Prometheus scrape target
    dashboards:
      - overview:                       # 全局概览
          - events_per_second           # 折线图
          - active_sessions             # 仪表盘
          - storage_bytes               # 仪表盘
          - active_agents               # 列表
      - llm_calls:                      # LLM 调用详情
          - tokens_per_minute           # 折线图 (分 provider)
          - cost_per_hour               # 柱状图
          - latency_p50_p95_p99         # 分位数
          - top_models                  # Top-N 排名
      - policy:                         # 策略统计
          - denies_per_hour             # 折线图
          - top_blocked_rules           # Top-N
          - approval_rate               # 仪表盘

  # ── 合规视图 (Svelte SPA) ──
  compliance:
    spa_build: frontend/dist/           # 静态文件
    pages:
      - /                              # 概览: 全局状态
      - /events                        # 事件搜索 + 明细
      - /sessions/:id                  # Session 回放
      - /prompts/:agent_id             # 提示词版本时间线
      - /evidence                      # 证据包导出
      - /report                        # EU AI Act 报告生成
      - /integrity                     # 链完整性验证
    api:
      - GET /api/v1/events?filter      # 事件查询
      - GET /api/v1/sessions           # Session 列表
      - GET /api/v1/sessions/:id       # Session 详情
      - GET /api/v1/prompts/:agent     # 提示词历史
      - POST /api/v1/evidence/export   # 创建证据包
      - GET /api/v1/compliance/report  # 合规报告
      - POST /api/v1/verify            # 触发完整性校验
```

### 3.5 API 层升级

当前 REST API 基于 `http.server`(stdlib)，需要升级到 FastAPI：

```python
# ── v1.0 REST API 设计 (FastAPI) ──

from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

app = FastAPI(title="agent-audit API", version="1.0.0")
security = HTTPBearer()

# 中间件
app.add_middleware(PrometheusMiddleware)      # 自动采集 /metrics
app.add_middleware(CORSMiddleware, ...)       # CORS
app.add_middleware(GZipMiddleware)            # 压缩

# ── 日志 API ──
POST   /api/v1/log                          # 记录事件
POST   /api/v1/log/batch                    # 批量记录
GET    /api/v1/events                       # 查询事件
GET    /api/v1/events/:event_id             # 事件详情

# ── Session API ──
GET    /api/v1/sessions                     # 所有 session
GET    /api/v1/sessions/:id                 # session 详情
GET    /api/v1/sessions/:id/events          # session 事件
GET    /api/v1/sessions/:id/verify          # 验证 session 链

# ── Agent API ──
GET    /api/v1/agents                       # 所有 agent
GET    /api/v1/agents/:id/stats             # agent 统计

# ── Prompt API ──
GET    /api/v1/prompts/:agent_id            # 提示词版本列表
POST   /api/v1/prompts/:agent_id            # 保存新版本
GET    /api/v1/prompts/:agent_id/diff       # 版本对比

# ── 策略 API ──
GET    /api/v1/policy/rules                 # 规则列表
POST   /api/v1/policy/evaluate              # 评估某输出

# ── 合规 API ──
POST   /api/v1/evidence/export              # 导出证据包
GET    /api/v1/compliance/report            # 生成合规报告
POST   /api/v1/verify                       # 全局完整性验证

# ── LLM 调用 API (v1.0 新增) ──
POST   /api/v1/llm/log                      # 记录 LLM 调用
GET    /api/v1/llm/traces/:trace_id         # 查询追踪链
GET    /api/v1/llm/stats                    # Token/成本统计

# ── 运维 API ──
GET    /metrics                             # Prometheus metrics
GET    /health                              # 健康检查
GET    /ready                               # 就绪检查
```

---

## 4. LLM 调用链自动追踪

### 4.1 方案对比

| 维度 | 方案 A: 手动装饰器 | 方案 B: Monkey-patch OpenAI/Anthropic SDK | 方案 C: OpenTelemetry Instrumentation |
|------|-------------------|------------------------------------------|---------------------------------------|
| **侵入度** | 高 — 每处调用加装饰器 | 中 — import 时自动 patch | 低 — 标准 OTel 体系 |
| **兼容性** | 无 | OpenAI SDK / Anthropic SDK | 全部 (支持 100+ SDK) |
| **追踪粒度** | 单次调用 | 请求-响应 | 完整分布式追踪 |
| **可观测性** | 仅 agent-audit | agent-audit + 日志 | 全栈 (链路追踪 + 指标 + 日志) |
| **与现有系统集成** | 自建 | 自建 | Grafana Tempo / Jaeger / Datadog |
| **开发成本** | 低 | 中 | 中高 |
| **推荐度** | ❌ | ⭐⭐⭐ 初期 | ⭐⭐⭐⭐⭐ 长期 |

### 4.2 推荐方案：方案 B → C 渐进

**初期 (v1.0-alpha)** — Monkey-patch 方案，快速见效：

```python
# agent_audit/tracing/auto.py
# 一行启用
import agent_audit.tracing.auto  # auto-instrument OpenAI & Anthropic

# 之后所有 LLM 调用自动记录到 audit trail + llm_calls 表
```

```python
# agent_audit/tracing/openai_instrumentor.py

import json
import time
from opentelemetry import trace
from functools import wraps

class OpenAITraceInstrumentor:
    """Auto-instrument OpenAI Python SDK calls."""

    def __init__(self, engine: "AuditEngine", tracer=None):
        self.engine = engine
        self.tracer = tracer or trace.get_tracer("agent-audit")

    def install(self):
        """Monkey-patch openai.ChatCompletion.create and friends."""
        import openai
        original_create = openai.ChatCompletion.create

        @wraps(original_create)
        async def traced_create(*args, **kwargs):
            span_name = f"llm/{kwargs.get('model', 'unknown')}"

            with self.tracer.start_as_current_span(span_name) as span:
                start = time.time()
                try:
                    result = await original_create(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    raise

                duration = time.time() - start

                # Extract telemetry
                usage = result.get("usage", {})
                model = kwargs.get("model", "unknown")
                messages = kwargs.get("messages", [])

                # Record in llm_calls table
                self.engine.record_llm_call(
                    trace_id=span.get_span_context().trace_id,
                    span_id=span.get_span_context().span_id,
                    parent_span_id=span.parent.span_id if span.parent else "",
                    provider="openai",
                    model=model,
                    request_tokens=usage.get("prompt_tokens", 0),
                    response_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    latency_ms=int(duration * 1000),
                    cost_usd=estimate_openai_cost(model, usage),
                    request_body={"messages": messages[-2:]},  # 只保留最近两轮
                    response_body={"choices": result.get("choices", [])[:1]},
                    session_id=extract_session(kwargs),
                    agent_id=extract_agent(kwargs),
                )

                # Also log to audit trail
                if kwargs.get("audit", True):
                    self.engine.log(
                        session_id=extract_session(kwargs),
                        event_type="model_request",
                        agent_id=extract_agent(kwargs),
                        prompt_version=kwargs.get("prompt_version", "unknown"),
                        input_text=json.dumps(messages[-1])[:4000],
                        output_text=str(result["choices"][0]["message"]["content"])[:4000],
                        metadata={
                            "model": model,
                            "tokens": usage.get("total_tokens", 0),
                            "latency_ms": int(duration * 1000),
                            "cost_usd": cost_usd,
                        },
                    )

                return result

        openai.ChatCompletion.create = traced_create
```

**长期 (v1.0)** — 迁移到 OpenTelemetry SDK Instrumentation：

```python
# agent_audit/tracing/opentelemetry.py
# 使用标准 OTel 体系

from opentelemetry.instrumentation.openai import OpenAIInstrumentor
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.exporter.otlp.proto.grpc.exporter import OTLPSpanExporter

# 职责:
# 1. OTel SDK 自动捕获 LLM 调用 (span/trace)
# 2. OTel SpanProcessor → 写入 llm_calls 表
# 3. OTel 原生导出到 Tempo / Jaeger / Datadog
# 4. agent-audit 同时从 trace 中提取审计事件

class AuditSpanProcessor(SpanProcessor):
    """将 OTel spans 同步写入 audit trail + llm_calls 表。"""

    def __init__(self, engine: "AuditEngine"):
        self.engine = engine

    def on_end(self, span: ReadableSpan):
        if span.attributes.get("llm.model"):
            self.engine.record_llm_call_from_span(span)
            if span.attributes.get("audit.enabled", True):
                self.engine.log_from_span(span)
```

### 4.3 追踪数据流

```
Agent App
    │
    ├─ openai.ChatCompletion.create(...)
    │       │
    │       ▼ Monkey-patch / OTel Instrumentation
    │       │
    │       ├─▶ llm_calls 表 ───▶ Dashboard LLM 视图
    │       │       │
    │       │       └─▶ 成本统计 / Token 统计 / 延迟分析
    │       │
    │       └─▶ events 表 ───▶ 哈希链审计
    │               │
    │               └─▶ 完整性验证 / 证据包
    │
    └─ (可选) OTel Exporter ──▶ Grafana Tempo / Jaeger
```

### 4.4 零侵入使用方式

```python
# 用户在项目入口处一行启用：
import agent_audit.tracing  # 自动 patch OpenAI & Anthropic

# 或者通过环境变量：
# export AGENT_AUDIT_AUTO_TRACE=1
```

```python
# 如果用户需要更细粒度控制：
from agent_audit.tracing import TraceConfig, OpenAIInstrumentor, AnthropicInstrumentor

config = TraceConfig(
    auto_audit=True,          # 自动写入 audit trail
    auto_cost=True,           # 自动计算成本
    pii_redact=True,          # 自动脱敏请求/响应
    max_prompt_len=4000,      # prompt 截断长度
)

openai_tracer = OpenAIInstrumentor(config)
openai_tracer.install()  # 只 patch OpenAI
```

---

## 5. 企业部署架构

### 5.1 方案对比

| 维度 | 方案 A: Docker Compose (单机) | 方案 B: K8s (小型集群) | 方案 C: K8s (生产级) |
|------|-------------------------------|------------------------|----------------------|
| **节点数** | 1 | 3-5 | 5+ |
| **高可用** | ❌ (单点) | ✅ (多副本) | ✅ (多AZ) |
| **自动扩缩** | ❌ | ✅ HPA | ✅ HPA + VPA |
| **备份恢复** | ✅ (cron + pg_dump) | ✅ (Velero + PG CR) | ✅ (Velero + PITR) |
| **成本** | ~¥100/月 (轻量云) | ~¥500/月 (3节点) | ~¥2000+/月 |
| **运维门槛** | 低 | 中 | 高 |
| **推荐场景** | 开发/小团队 | 中型团队 (<10 agent) | 大型企业 (>10 agent) |

### 5.2 推荐方案：渐进式

**初期 (v1.0)** → **方案 A: Docker Compose**

```
┌─────────────────────────────────────────────────┐
│                    Docker Compose               │
│                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│  │  nginx   │──▶│ FastAPI  │──▶│PostgreSQL│   │
│  │ (proxy+  │   │ (API +   │   │ (events) │   │
│  │  SSL)    │   │  Grafana?)│   └──────────┘   │
│  └──────────┘   └──────────┘                   │
│       │                                         │
│       ▼                                         │
│  ┌──────────┐  ┌──────────────┐                │
│  │  Svelte  │  │  Prometheus  │                │
│  │  SPA     │  │  (可选)      │                │
│  └──────────┘  └──────────────┘                │
└─────────────────────────────────────────────────┘
```

**生产 (v1.0+)** → **方案 B: K8s Helm Chart**

```
┌──────────────────────────────────────────────────────────┐
│                    K8s Namespace: agent-audit            │
│                                                           │
│  ┌──────────────┐                                        │
│  │  Ingress     │─── gRPC + HTTP                        │
│  │  (traefik)   │                                        │
│  └──────┬───────┘                                        │
│         │                                                │
│  ┌──────▼───────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  api-server  │  │  dashboard   │  │  grafana     │  │
│  │  (FastAPI)   │  │  (Svelte)    │  │  (运维面板)   │  │
│  │  replicas:2  │  │  replicas:1  │  └──────┬───────┘  │
│  └──────┬───────┘  └──────────────┘         │          │
│         │                                    │          │
│  ┌──────▼───────┐                 ┌──────────▼───────┐ │
│  │  PostgreSQL  │                 │   Prometheus     │ │
│  │  (CloudNativePG 或 RDS)       │   (kube-prometheus)│ │
│  └──────────────┘                 └──────────────────┘ │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │  Redis       │  │  S3/MinIO   │                     │
│  │  (缓存+锁)   │  │ (证据包存储) │                    │
│  └──────────────┘  └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

### 5.3 Docker Compose 配置 (v1.0)

```yaml
version: "3.8"

services:
  # ── 反向代理 ──
  nginx:
    image: nginx:1.27-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./agent_audit/server/static:/usr/share/nginx/html:ro
    depends_on: [api]
    restart: unless-stopped

  # ── API 服务 ──
  api:
    build:
      context: .
      dockerfile: Dockerfile
      target: production
    environment:
      - AGENT_AUDIT_DB_URL=postgresql://audit:${DB_PASSWORD}@db:5432/agent_audit
      - AGENT_AUDIT_REDIS_URI=redis://redis:6379/0
      - AGENT_AUDIT_SECRET_KEY=${SECRET_KEY}
      - AGENT_AUDIT_SIGNING_KEY=/run/secrets/signing_key
      - AGENT_AUDIT_AUTO_TRACE=${AUTO_TRACE:-1}
    secrets:
      - signing_key
    depends_on: [db, redis]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 3

  # ── 数据库 ──
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: audit
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: agent_audit
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U audit"]
      interval: 10s
      timeout: 3s

  # ── 缓存 ──
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    restart: unless-stopped

  # ── 备份 ──
  backup:
    image: postgres:16-alpine
    entrypoint: ["/bin/sh", "-c"]
    command: |
      "0 3 * * * pg_dump -h db -U audit agent_audit | gzip > /backups/agent-audit-$$(date +\\%Y\\%m\\%d).sql.gz"
    environment:
      PGPASSWORD: ${DB_PASSWORD}
    volumes:
      - backups:/backups
    depends_on: [db]

  # ── Prometheus (可选) ──
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
    restart: unless-stopped

volumes:
  pgdata:
  redis-data:
  backups:
  prometheus-data:

secrets:
  signing_key:
    file: ./secrets/ed25519_private.pem
```

### 5.4 K8s Helm Chart 结构 (v1.0+)

```
deploy/charts/agent-audit/
├── Chart.yaml               # chart 元数据
├── values.yaml              # 默认值
├── values-prod.yaml         # 生产覆盖
├── templates/
│   ├── _helpers.tpl         # 模板辅助
│   ├── deployment-api.yaml  # API 部署
│   ├── deployment-dashboard.yaml
│   ├── service.yaml         # Service
│   ├── ingress.yaml         # Ingress
│   ├── configmap.yaml       # 非敏感配置
│   ├── secret.yaml          # 敏感配置
│   ├── hpa.yaml             # 自动扩缩
│   ├── pdb.yaml             # PodDisruptionBudget
│   ├── pvc.yaml             # 持久卷
│   ├── network-policy.yaml  # 网络策略
│   └── service-monitor.yaml # Prometheus Operator
└── README.md
```

### 5.5 环境变量配置 (.env)

```bash
# ── 核心配置 ──
AGENT_AUDIT_DB_URL=postgresql://audit:PASSWORD@db:5432/agent_audit
AGENT_AUDIT_REDIS_URI=redis://redis:6379/0
AGENT_AUDIT_SECRET_KEY=<随机64字节hex>

# ── 存储 ──
AGENT_AUDIT_STORAGE_BACKEND=postgresql    # jsonl|sqlite|postgresql
AGENT_AUDIT_EVIDENCE_STORE=s3://bucket    # 证据包存储 (可选)

# ── 加密 & 签名 ──
AGENT_AUDIT_SIGNING_KEY=/etc/secrets/ed25519.pem
AGENT_AUDIT_ENCRYPTION_KEY=<32字节hex>    # AES-256

# ── LLM 追踪 ──
AGENT_AUDIT_AUTO_TRACE=1                  # 启用自动追踪
AGENT_AUDIT_TRACE_PII_REDACT=1            # 脱敏 LLM 请求
AGENT_AUDIT_TRACE_MAX_LEN=4000            # 截断长度
AGENT_AUDIT_TRACE_COST_MODEL=openai       # 成本计算模型

# ── API ──
AGENT_AUDIT_API_KEYS=key1,key2            # 可选 API keys
AGENT_AUDIT_CORS_ORIGINS=*                # CORS

# ── 通知 ──
AGENT_AUDIT_SLACK_WEBHOOK=https://hooks.slack.com/...
AGENT_AUDIT_SMTP_HOST=smtp.example.com
AGENT_AUDIT_NOTIFY_ON_FAILURE=1

# ── 日志 ──
AGENT_AUDIT_LOG_LEVEL=info
AGENT_AUDIT_LOG_FORMAT=json               # json|text
```

---

## 6. 产品化路线图

### 6.1 v0.1 → v1.0 → 商业化路径

```
                   2026 Q2            2026 Q3             2026 Q4            2027 Q1
                      │                  │                   │                  │
  v0.1  ──────────────┤                  │                   │                  │
  (SHA-256 哈希链)    │                  │                   │                  │
  JSONL + SQLite      │                  │                   │                  │
  CLI + Dashboard     │                  │                   │                  │
                      ▼                  │                   │                  │
              ┌──────────────────┐       │                   │                  │
              │     v1.0-alpha   │       │                   │                  │
              │  (2026-07)       │       │                   │                  │
              │  - PG 存储       │       │                   │                  │
              │  - FastAPI + SPA │       │                   │                  │
              │  - 自动追踪      │       │                   │                  │
              │  - Docker Compose│       │                   │                  │
              └────────┬─────────┘       │                   │                  │
                       │                 ▼                   │                  │
                       │         ┌──────────────────┐        │                  │
                       └────────▶│    v1.0-RC       │        │                  │
                                 │  (2026-08)       │        │                  │
                                 │  - Helm Chart    │        │                  │
                                 │  - Grafana 面板  │        │                  │
                                 │  - 策略 UI        │        │                  │
                                 │  - REST API v1   │        │                  │
                                 └────────┬─────────┘        │                  │
                                          │                  ▼                  │
                                          │          ┌──────────────────┐      │
                                          └─────────▶│   v1.0 Stable    │      │
                                                      │  (2026-09)       │      │
                                                      │  - RBAC          │      │
                                                      │  - Audit Log     │      │
                                                      │  - E2E Tests     │      │
                                                      └────────┬─────────┘      │
                                                               │                ▼
                                                               │        ┌──────────────────┐
                                                               └───────▶│    v2.0 商业化    │
                                                                        │  (2027-Q1)       │
                                                                        │  - 团队版订阅     │
                                                                        │  - 企业 SSO       │
                                                                        │  - SLA            │
                                                                        │  - 私有部署        │
                                                                        └──────────────────┘
```

### 6.2 v1.0 里程碑

| 里程碑 | 时间 | 关键交付物 | 验收标准 |
|--------|------|-----------|---------|
| **M1: PostgreSQL+API 升级** | 2026-07-15 | PostgreSQL store + FastAPI + .env | 旧 JSONL/SQLite 用户无感迁移 |
| **M2: Dashboard 重构** | 2026-08-01 | Svelte SPA + Grafana 预置面板 | 运维+合规双视图可用 |
| **M3: 自动追踪** | 2026-08-15 | OpenAI/Anthropic auto-instrument | 用户一行代码启用 |
| **M4: K8s 部署** | 2026-08-30 | Helm Chart + Docker Compose 升级 | 一键部署到 K8s |
| **M5: v1.0 Stable** | 2026-09-30 | 完整文档 + E2E 测试 + 性能基线 | 全链路可用 |

### 6.3 商业化模式 (v2.0 方向)

```yaml
commercial_tiers:
  community:
    price: 免费 (MIT License)
    features:
      - 全部开源代码
      - JSONL / SQLite 存储
      - CLI + Web Dashboard
      - 社区支持 (Discord)

  team:
    price: ¥299/月 (或 ¥2999/年)
    features:
      - PostgreSQL 存储
      - LLM 自动追踪 (OpenAI + Anthropic)
      - 合规报告自动生成
      - Slack / Email / Webhook 通知
      - 策略引擎 UI
      - Email 支持

  enterprise:
    price: 定制报价
    features:
      - 私有化部署 (Docker / K8s)
      - 企业 SSO (SAML / OIDC)
      - SLA 99.9%
      - 专属支撑团队
      - 自定义合规报告
      - 专属私有插件
      - 审计员多租户
      - 数据保留策略配置
```

### 6.4 差异化定位

```
                    ┌─────────────────────────────────────┐
                    │         agent-audit 差异化          │
                    ├─────────────────────────────────────┤
                    │                                     │
                    │  LangSmith / LangFuse / LangWatch   │
                    │     ↓                               │
                    │  执行追踪 + 可观测性                  │
                    │     ✗ 防篡改哈希链                    │
                    │     ✗ Ed25519 签名                   │
                    │     ✗ 证据包离线验证                  │
                    │     ✗ EU AI Act 合规报告             │
                    │                                     │
                    │  agent-audit                        │
                    │     ↓                               │
                    │  执行追踪 + 可观测性 (基础)           │
                    │     + 防篡改哈希链 (核心)             │
                    │     + Ed25519 签名 (可选)            │
                    │     + 离线证据包                     │
                    │     + 合规报告                       │
                    │     + 策略引擎                       │
                    │                                     │
                    │  ★ 唯一为 EU AI Act 设计的开源方案    │
                    └─────────────────────────────────────┘
```

---

## 7. 方案评估与风险

### 7.1 技术风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| PostgreSQL 性能不满足写入峰值 | 低 | 高 | 写入缓冲 + 批量插入 + 异步写入 |
| OTel 自动追踪导致 LLM 调用延迟增加 | 中 | 中 | 异步 SpanProcessor + 可选关闭 |
| 用户不愿意升级存储后端 | 中 | 中 | 保持 JSONL/SQLite backend 兼容 |
| Dashboard SPA 维护成本高 | 中 | 低 | 优先 Grafana + 渐进式 SPA |
| K8s 部署过于复杂 | 中 | 中 | 保留 Docker Compose + Helm 两种选择 |

### 7.2 向后兼容性

| 变更 | 破坏性 | 迁移策略 |
|------|--------|----------|
| `trail.log()` 签名不变 | ✅ 无 | 保持参数兼容 |
| `AuditStore` 接口新增方法 | ⚠️ 轻微 (继承需更新) | 提供默认实现 |
| JSONL 数据格式不变 | ✅ 无 | 仅新增字段 |
| CLI 命令不变 | ✅ 无 | 保持兼容 |
| Docker Compose 升级 | ⚠️ 需改 .env | 提供迁移脚本 |
| REST API 升级到 /api/v1/ | ⚠️ 路径变更 | v0 API 保留 6 个月 |

### 7.3 关键决策记录

```
ADR-001: 选择 PostgreSQL 为主存储
  理由: 企业级审计系统必须支持 SQL 查询 + ACID 事务
  备选: MongoDB → 不支持 JOIN 审计查询
  备选: TimescaleDB → 初期过重，后续加

ADR-002: 选择 FastAPI 替代 http.server
  理由: 内置 OpenAPI 文档 + Pydantic 校验 + 性能
  备选: Flask → 缺少异步支持
  备选: Starlette → 无框架功能太薄

ADR-003: LLM 追踪选择 OpenTelemetry 体系
  理由: 标准生态，未来可扩展到 100+ SDK
  备选: 自建 → 维护成本高，功能局限
  备选: LangSmith SDK → 依赖外部服务

ADR-004: Dashboard 选择 Grafana + 轻量 SPA
  理由: 运维视图用成熟工具，合规视图自建
  备选: 全自建 SPA → 运维视图重造轮子
  备选: 纯 Grafana → 合规视图定制受限
```

---

## 8. 实施计划

### 8.1 任务分解

```
Phase 1 — 存储升级 & API (预计 3 周)
├── P1.1  PostgreSQL Schema 设计与实现
├── P1.2  AuditStore PostgreSQL backend 实现
├── P1.3  FastAPI 迁移 (替代 http.server)
├── P1.4  .env 配置系统
├── P1.5  迁移脚本: JSONL → PG / SQLite → PG
└── P1.6  E2E 测试 + 性能基准

Phase 2 — Dashboard & 合规 (预计 3 周)
├── P2.1  Svelte SPA 框架搭建
├── P2.2  合规视图 (链验证 / 提示词 / 证据包)
├── P2.3  API v1 文档 (OpenAPI)
├── P2.4  Grafana JSON 面板预置
└── P2.5  Prometheus + 自定义指标

Phase 3 — LLM 自动追踪 (预计 2 周)
├── P3.1  OpenAI Instrumentor
├── P3.2  Anthropic Instrumentor
├── P3.3  llm_calls 表 + 统计数据 API
├── P3.4  OTel Span → AuditEvent 桥接
└── P3.5  成本计算模型

Phase 4 — 部署 & 文档 (预计 2 周)
├── P4.1  Docker Compose 升级
├── P4.2  Helm Chart 编写
├── P4.3  配置文档 + 快速开始指南
└── P4.4  性能测试报告

Phase 5 — 稳定性 & 发布 (预计 2 周)
├── P5.1  E2E 测试全覆盖
├── P5.2  安全审计
├── P5.3  v1.0 Release Note
└── P5.4  用户迁移指南
```

### 8.2 代码仓库结构 (v1.0)

```
agent-audit/
├── agent_audit/
│   ├── __init__.py             # v1.0.0
│   ├── engine.py               # [NEW] AuditEngine (统一入口)
│   ├── trail.py                # [KEEP] 兼容层 → 委托 engine
│   ├── storage.py              # [DEPRECATE] → 委托 engine
│   │
│   ├── core/
│   │   ├── chain.py            # [KEEP] SessionChain
│   │   ├── storage.py          # [REFACTOR] + PostgreSQLStore
│   │   ├── crypto.py           # [KEEP] Ed25519
│   │   ├── encrypted.py        # [KEEP] AES-256-GCM
│   │   ├── redact.py           # [KEEP] PII 脱敏
│   │   └── rotation.py         # [KEEP] 日志轮转
│   │
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py              # [NEW] FastAPI app
│   │   ├── routes/
│   │   │   ├── events.py       # [NEW] 事件路由
│   │   │   ├── sessions.py     # [NEW] Session 路由
│   │   │   ├── prompts.py      # [NEW] 提示词路由
│   │   │   ├── compliance.py   # [NEW] 合规路由
│   │   │   ├── llm.py          # [NEW] LLM 追踪路由
│   │   │   └── admin.py        # [NEW] 管理路由
│   │   ├── middlewares.py      # [NEW] 中间件
│   │   └── metrics.py          # [KEEP] Prometheus
│   │
│   ├── tracing/
│   │   ├── __init__.py         # [NEW] import 即启用
│   │   ├── openai.py           # [NEW] OpenAI Instrumentor
│   │   ├── anthropic.py        # [NEW] Anthropic Instrumentor
│   │   ├── opentelemetry.py    # [NEW] OTel SpanProcessor
│   │   └── cost.py             # [NEW] 成本计算
│   │
│   ├── dashboard/              # [NEW] SPA 构建产物
│   ├── cli.py                  # [UPDATE] + 新命令
│   ├── migrate.py              # [KEEP] 迁移工具
│   │
│   ├── policy/                 # [KEEP] 策略引擎
│   ├── integrations/           # [KEEP] 集成
│   └── hooks/                  # [KEEP] 通知
│
├── frontend/                   # [NEW] Svelte SPA 源码
├── deploy/
│   ├── docker-compose.yml      # [UPDATE] 生产级
│   ├── Dockerfile              # [UPDATE] 多阶段
│   ├── charts/                 # [NEW] Helm Chart
│   └── init.sql                # [NEW] 数据库初始化
│
├── docs/
│   ├── architecture-v1.md      # [NEW] 本文档
│   ├── migration-guide.md      # [TODO] 迁移指南
│   └── api-v1.md               # [TODO] API 文档
│
├── tests/
├── requirements.txt            # [UPDATE]
└── README.md                   # [UPDATE]
```

---

## 附录 A: 性能基准目标 (v1.0)

| 场景 | 当前 v0.1 (JSONL) | v1.0 目标 (PG) | v1.0 目标 (PG+TSC) |
|------|-------------------|----------------|-------------------|
| 单事件写入 | ~2,000/s | ~5,000/s | ~50,000/s |
| 批量写入 (100/batch) | N/A | ~20,000/s | ~100,000/s |
| Session 查询 (1000 events) | ~50ms | ~5ms | ~2ms |
| 全局验证 (100K events) | ~2s | ~200ms | ~100ms |
| 事件搜索 (全文) | ~500ms | ~20ms | ~15ms |
| 证据包导出 (10K events) | ~1s | ~500ms | ~500ms |

## 附录 B: 技术栈选型总结

| 组件 | v0.1 | v1.0 | 理由 |
|------|------|------|------|
| **Web 框架** | http.server | FastAPI | 性能 + OpenAPI + Pydantic |
| **数据库** | JSONL / SQLite | PostgreSQL | ACID + SQL + 企业级 |
| **监控** | 内联指标 | Prometheus + Grafana | 标准生态 |
| **追踪** | 无 / 手动 | OpenTelemetry | 标准 + 可扩展 |
| **前端** | 内联 HTML | Svelte (可选) + Grafana | 轻量 + 专业运维面板 |
| **容器化** | Docker (单阶段) | Docker (多阶段) + Helm | 生产级别部署 |
| **配置** | 硬编码 | .env + ConfigMap | 12 Factor App |
| **Python 版本** | 3.10+ | 3.11+ | 支持最新语法 |
