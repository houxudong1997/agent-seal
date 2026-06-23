# agent-audit / AI Agent 审计追踪

**Tamper-proof audit trail for AI agents / 防篡改的 AI Agent 审计追踪** — three-line integration (zero-code hook, `@observe` decorator, or framework callback). EU AI Act Article 12 ready. / 三行代码即可集成（零代码 Hook、`@observe` 装饰器或框架回调）。已为 EU AI Act 第 12 条做好准备。

> English | 中文

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://pypi.org/project/agent-audit/)

agent-audit records every decision, tool call, and model request an AI agent makes into an immutable, SHA-256 hash-chained log. Each event is cryptographically linked to the previous one — tamper with a single byte and the entire chain breaks, detected instantly on verification. Designed for **EU AI Act Article 12** (record-keeping, effective August 2026), SOC 2, and HIPAA audit requirements.

agent-audit 将 AI Agent 的每一次决策、工具调用和模型请求记录到一个不可篡改的、由 SHA-256 哈希链串联的日志中。每个事件都通过密码学方式与前一个事件链接——篡改任意一个字节，整条链就会断裂，验证时即刻被发现。专为 **EU AI Act 第 12 条**（记录保存，2026 年 8 月生效）、SOC 2 和 HIPAA 审计要求而设计。

---

## Integration Methods / 集成方式 🆕

agent-audit v1.1 offers three integration paths — from zero-code to deep framework hooks. Pick the one that fits your stack.

agent-audit v1.1 提供三种集成方式——从零代码到深度框架钩子。选择适合你技术栈的方式。

| Method / 方式 | Code Required / 代码量 | What It Captures / 捕获内容 | Best For / 适用场景 |
|--------|:------------:|------------------|----------|
| **Zero-code hook / 零代码 Hook** | None / 无需代码 | All LLM calls in every Python process / 所有 Python 进程中的 LLM 调用 | Existing apps, no-code compliance / 存量应用，无代码合规 |
| **`@observe` decorator / @observe 装饰器** | 1 import + 1 line / 1 个导入 + 1 行 | Any Python function (inputs, outputs, latency) / 任意 Python 函数（输入、输出、延迟） | Precise function-level tracing / 精确的函数级追踪 |
| **Framework callbacks / 框架回调** | 1 import + 1 line / 1 个导入 + 1 行 | LangChain LCEL / Hermes Agent actions / LangChain LCEL / Hermes Agent 动作 | LangChain & Hermes users / LangChain 和 Hermes 用户 |

---

## Quick Start / 快速开始

### 1. Zero-Code (Global Hook) / 零代码（全局 Hook） 🆕

Install agent-audit and start the server. Every Python process on the machine is automatically traced — no code changes.

安装 agent-audit 并启动服务。机器上的每个 Python 进程都会被自动追踪——无需任何代码变更。

```bash
pip install agent-audit
agent-audit server
# Dashboard at http://localhost:8081 — all LLM calls appear automatically
# 控制台地址：http://localhost:8081 — 所有 LLM 调用自动出现
```

The global `sitecustomize.py` hook intercepts `httpx`-based LLM calls (OpenAI, Anthropic, and any OpenAI-compatible API) in every Python process. Works with frameworks, scripts, notebooks — anything that imports `openai` or `anthropic`.

全局 `sitecustomize.py` Hook 会在每个 Python 进程中拦截基于 `httpx` 的 LLM 调用（OpenAI、Anthropic 及任何兼容 OpenAI 的 API）。适用于框架、脚本、Notebook——任何导入了 `openai` 或 `anthropic` 的代码。

### 2. @observe Decorator / @observe 装饰器 🆕

Trace any Python function with one decorator. Inputs, outputs, execution time, and nested call trees are recorded into the audit trail.

一行装饰器即可追踪任意 Python 函数。输入、输出、执行时间和嵌套调用树都会被记录到审计追踪中。

```python
from agent_audit import observe, set_engine
from agent_audit.engine import AuditEngine

engine = AuditEngine("sqlite://audit.db")
set_engine(engine)

@observe(name="process_refund", metadata={"tier": "critical"})
def process_refund(order_id: str, amount: float) -> dict:
    user = lookup_user(order_id)
    result = issue_refund(user, amount)
    return result

# Nested calls are auto-linked as parent-child spans
# 嵌套调用自动关联为父子 Span
@observe(name="lookup_user")
def lookup_user(order_id: str) -> dict: ...

@observe(name="issue_refund")
def issue_refund(user: dict, amount: float) -> dict: ...

process_refund("ORD-123", 45.00)
# → 3 audit events: process_refund → lookup_user, process_refund → issue_refund
#   with parent_span_id linking inner calls to outer
# → 3 个审计事件：process_refund → lookup_user, process_refund → issue_refund
#   通过 parent_span_id 将内部调用链接到外部调用
```

### 3. LangChain Callback / LangChain 回调 🆕

One line registers a callback handler that audits every LLM call, tool invocation, chain step, and agent decision.

一行代码注册回调处理器，审计每一次 LLM 调用、工具调用、Chain 步骤和 Agent 决策。

```python
from agent_audit.hooks.langchain import LangChainAuditHandler

handler = LangChainAuditHandler(agent_id="my-agent")

from langchain.agents import AgentExecutor
executor = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
```

| Callback / 回调 | Event Type / 事件类型 |
|----------|-----------|
| `on_llm_start/end` | `model_request` |
| `on_tool_start/end` | `tool_call` |
| `on_chain_start/end` | `chain_step` |
| `on_agent_action/finish` | `decision` |

Token counts, latency, model name, and errors are captured automatically.

Token 消耗、延迟、模型名称和错误信息均被自动捕获。

### 4. Hermes Middleware / Hermes 中间件 🆕

Native support for the [Hermes Agent](https://hermes-agent.nousresearch.com/docs) framework. Zero-config — install and it auto-instruments all agent actions.

原生支持 [Hermes Agent](https://hermes-agent.nousresearch.com/docs) 框架。零配置——安装后即自动插桩所有 Agent 动作。

```python
# hermes_middleware.py is auto-detected
# hermes_middleware.py 会被自动检测
# No code changes needed in your Hermes agent
# 无需修改你的 Hermes Agent 代码
```

> **Note**: `langchain` and `langchain-core` are optional dependencies. Install them separately: `pip install langchain langchain-core`. When unavailable, the module imports cleanly but raises a friendly `RuntimeError` with install instructions.
>
> **注意**：`langchain` 和 `langchain-core` 是可选依赖。需单独安装：`pip install langchain langchain-core`。当这些包不可用时，模块可以正常导入，但会抛出一个带有安装指引的友好 `RuntimeError`。

---

## Key Features / 核心特性

### Core Audit Trail / 核心审计追踪

- **Immutable Hash Chain / 不可篡改的哈希链** — SHA-256 chain linking every event. Break one link = tampering detected. / SHA-256 链条串联每个事件。断裂任一环节 = 篡改即被发现。
- **Ed25519 Digital Signatures / Ed25519 数字签名** — Cryptographic non-repudiation per event. / 每个事件的密码学不可否认性。
- **AES-256-GCM Encryption / AES-256-GCM 加密** — Transparent encryption at rest. / 透明的静态数据加密。
- **PII Redaction / PII 脱敏** — Automatic PII scrubbing (emails, phones, SSNs, credit cards) before storage. / 存储前自动脱敏 PII（邮箱、电话、社保号、信用卡）。

### v1.1 Highlights / v1.1 亮点 🆕

- **🆕 Zero-Code Global Hook / 零代码全局 Hook** — `sitecustomize.py` auto-instruments all Python processes. No imports, no decorators, no config. / `sitecustomize.py` 自动插桩所有 Python 进程。无需导入、无需装饰器、无需配置。
- **🆕 @observe Decorator / @observe 装饰器** — Lightweight function tracing with nested span trees, latency, and custom metadata. / 轻量级函数追踪，支持嵌套 Span 树、延迟和自定义元数据。
- **🆕 LangChain CallbackHandler / LangChain 回调处理器** — Native `LangChainAuditHandler` for LCEL chains, agents, and tools. / 原生 `LangChainAuditHandler`，支持 LCEL Chain、Agent 和工具。
- **🆕 Hermes Middleware / Hermes 中间件** — First-class Hermes Agent framework integration. / 一等公民级别的 Hermes Agent 框架集成。
- **🆕 Enhanced SPA Dashboard / 增强版 SPA 控制台** — Expandable event details, smart previews, model/latency columns, binary output filtering. / 可展开的事件详情、智能预览、模型/延迟列、二进制输出过滤。

### Governance & Compliance / 治理与合规

- **Policy Engine / 策略引擎** — YAML-based guardrail rules. Block dangerous tool calls before execution. / 基于 YAML 的护栏规则。在危险工具调用执行前将其阻止。
- **Evidence Bundles / 证据包** — Export signed `.zip` bundles for external auditors with SHA-256 verification. / 导出带签名的 `.zip` 证据包，供外部审计师使用，附带 SHA-256 验证。
- **EU AI Act Reports / EU AI Act 报告** — Generate Article 12 compliance reports on demand (`agent-audit report <agent>`). / 按需生成第 12 条合规报告（`agent-audit report <agent>`）。
- **Prompt Version Tracking / Prompt 版本追踪** — Git-like prompt history with diffs — who changed what, when, and why. / 类 Git 的 Prompt 历史记录，支持差异对比——谁在何时因何原因修改了什么。

### Observability / 可观测性

- **LLM Auto-Tracing / LLM 自动追踪** — Monkey-patch instrumentation for OpenAI, Anthropic, OpenTelemetry. Token counts, latency, cost. / 针对 OpenAI、Anthropic、OpenTelemetry 的 Monkey-patch 插桩。Token 消耗、延迟、费用。
- **Prometheus Metrics / Prometheus 指标** — `GET /metrics` exporting `audit_events_total`, `audit_sessions_active`, `audit_policy_denials_total`. / `GET /metrics` 导出 `audit_events_total`、`audit_sessions_active`、`audit_policy_denials_total`。
- **Slack + Email Alerts / Slack + 邮件告警** — Notifications for policy blocks, integrity failures, error spikes. / 针对策略阻止、完整性失败、错误激增的通知。

### Storage / 存储

- **JSONL** — Zero-dependency file backend for development. / 零依赖文件后端，用于开发环境。
- **SQLite** — Single-file embedded database for small-scale deployments. / 单文件嵌入式数据库，用于小规模部署。
- **PostgreSQL** — Production-grade concurrent-safe storage with connection pooling and Alembic migrations. / 生产级并发安全存储，支持连接池和 Alembic 迁移。

---

## Installation / 安装

```bash
pip install agent-audit
```

With PostgreSQL support / 带 PostgreSQL 支持：

```bash
pip install agent-audit[postgresql]
```

Or everything / 或安装全部：

```bash
pip install agent-audit[all]
```

### From source / 从源码安装

```bash
git clone https://github.com/user/agent-audit.git
cd agent-audit
pip install -e .
```

---

## Dashboard / 控制台 🆕

> 📸 **Screenshot placeholder** — Dashboard screenshot coming soon. / **截图占位** — 控制台截图即将上线。

The SPA Dashboard provides real-time visibility into your audit trail:

SPA 控制台为你的审计追踪提供实时可视性：

- **Event list** with expandable detail rows — inputs, outputs, metadata / **事件列表**，支持展开详情行——输入、输出、元数据
- **Smart previews** — truncated long content with "Show more" / **智能预览**——截断长内容并显示"展开更多"
- **Model & latency columns** — at-a-glance performance monitoring / **模型与延迟列**——一目了然的性能监控
- **Binary/garbled output filtering** — clean display of structured data / **二进制/乱码输出过滤**——结构化数据的清晰展示
- **SSE live updates** — new events stream in real time, no page refresh / **SSE 实时更新**——新事件实时流式推送，无需刷新页面

Start the dashboard: `agent-audit server` → open `http://localhost:8081`

启动控制台：`agent-audit server` → 打开 `http://localhost:8081`

---

## Architecture / 架构

```
┌──────────────────────────────────────────────────────────────┐
│                   INTEGRATION LAYER / 集成层                   │
│                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  Zero-Code Hook  │  │  @observe    │  │ Framework Hooks  │ │
│  │  (sitecustomize) │  │  (decorator) │  │ (LangChain/Hermes)│ │
│  │                 │  │              │  │                  │ │
│  │  Auto-intercept  │  │  Manual trace│  │  Native callback │ │
│  │  all LLM calls   │  │  any function│  │  integration     │ │
│  └────────┬────────┘  └──────┬───────┘  └────────┬─────────┘ │
│           │                  │                    │           │
└───────────┼──────────────────┼────────────────────┼───────────┘
            │                  │                    │
            ▼                  ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                   AUDIT ENGINE / 审计引擎                      │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │Hash Chain│  │ Ed25519  │  │AES-256-GCM│  │ PII Redact   │ │
│  │ SHA-256  │  │Signatures│  │Encryption │  │              │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │           Storage Backends / 存储后端                  │    │
│  │     JSONL (dev)  │  SQLite (small)  │  PostgreSQL     │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────┬──────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   ┌────────────┐  ┌──────────────┐  ┌──────────────┐
   │  REST API  │  │SPA Dashboard │  │  Prometheus   │
   │  /api/v1/* │  │  :8081       │  │  /metrics     │
   └────────────┘  └──────────────┘  └──────────────┘
```

```
agent_audit/
├── trail.py              # Hash-chained audit trail (entry point) / 哈希链审计追踪（入口）
├── engine.py             # Unified AuditEngine (JSONL/SQLite/PG) / 统一审计引擎
├── observe.py            # @observe decorator / @observe 装饰器 🆕
├── config.py             # 12-Factor configuration / 12-Factor 配置
├── cli.py                # CLI commands / CLI 命令
├── core/
│   ├── chain.py          # SessionChain — per-session hash chains / 按会话的哈希链
│   ├── storage.py        # Storage backends (JSONL, SQLite, PostgreSQL) / 存储后端
│   ├── crypto.py         # Ed25519 signing / Ed25519 签名
│   ├── encrypted.py      # AES-256-GCM encryption / AES-256-GCM 加密
│   ├── redact.py         # PII redaction / PII 脱敏
│   └── rotation.py       # Log rotation / 日志轮转
├── server/
│   ├── app.py            # FastAPI application / FastAPI 应用
│   ├── hermes_middleware.py  # Hermes Agent middleware / Hermes Agent 中间件 🆕
│   └── routes/           # REST endpoints / REST 端点
├── policy/engine.py      # YAML-based guardrail rules / 基于 YAML 的护栏规则
├── tracing/              # LLM auto-instrumentation / LLM 自动插桩 (OpenAI, Anthropic, OTel)
├── hooks/
│   ├── langchain.py      # LangChain CallbackHandler / LangChain 回调处理器 🆕
│   ├── hermes_worker.py  # Hermes worker hook / Hermes Worker 钩子 🆕
│   ├── slack.py          # Slack notifications / Slack 通知
│   └── email.py          # Email alerts / 邮件告警
├── integrations/         # LangChain, MCP server adapters / LangChain、MCP 服务适配器
├── models/               # SQLAlchemy models / SQLAlchemy 模型
├── evidence.py           # Evidence bundle export / 证据包导出
├── report.py             # EU AI Act compliance reports / EU AI Act 合规报告
├── prompt_version.py     # Prompt version tracking / Prompt 版本追踪
├── replay.py             # Trail replay / 追踪回放
└── regression.py         # Regression testing / 回归测试
```

For detailed architecture see [docs/architecture-v1.md](docs/architecture-v1.md). / 详细架构请参阅 [docs/architecture-v1.md](docs/architecture-v1.md)。

---

## CLI Reference / CLI 参考

```bash
agent-audit <command> [options]
```

| Command / 命令   | Description / 描述                                    |
|-----------|------------------------------------------------|
| `server`  | Start API server + SPA Dashboard / 启动 API 服务 + SPA 控制台               |
| `verify`  | Check audit trail integrity (hash chain) / 检查审计追踪完整性（哈希链）       |
| `trail`   | Show recent events and statistics / 显示最近事件和统计信息              |
| `report`  | Generate EU AI Act Article 12 compliance report / 生成 EU AI Act 第 12 条合规报告 |
| `log`     | Record a test event / 记录一条测试事件                            |
| `prompt`  | Manage prompt versions (list, diff, audit) / 管理 Prompt 版本（列表、差异、审计）    |

---

## REST API

Start the server / 启动服务：

```bash
agent-audit server
# OR: uvicorn agent_audit.server.app:app --host 0.0.0.0 --port 8081
```

Endpoints / 端点：

| Method | Path                            | Description / 描述                    |
|--------|---------------------------------|--------------------------------|
| GET    | `/health`                       | Health check / 健康检查                   |
| POST   | `/api/v1/log`                   | Append an audit event / 追加一条审计事件          |
| GET    | `/api/v1/events`                | Query events (filter + search) / 查询事件（过滤 + 搜索） |
| GET    | `/api/v1/events/stream`         | SSE real-time event stream / SSE 实时事件流     |
| POST   | `/api/v1/verify`                | Verify chain integrity / 验证链完整性         |
| POST   | `/api/v1/compliance/report`     | Generate EU AI Act report / 生成 EU AI Act 报告      |
| GET    | `/api/v1/compliance/report/{id}`| Retrieve cached report / 获取缓存的报告         |
| GET    | `/api/v1/stats`                 | Aggregate statistics / 聚合统计           |
| GET    | `/api/v1/sessions`              | List audit sessions / 列出审计会话            |
| GET    | `/metrics`                      | Prometheus metrics / Prometheus 指标             |

---

## Configuration / 配置

All settings via environment variables (12-Factor App). See `.env.example` for a complete template.

所有设置均通过环境变量配置（12-Factor App）。完整模板参见 `.env.example`。

| Variable / 变量                          | Default / 默认值           | Description / 描述                             |
|-----------------------------------|-------------------|-----------------------------------------|
| `AGENT_AUDIT_DB_URL`              | _(auto-detect)_   | PostgreSQL / SQLite connection string / 数据库连接字符串   |
| `AGENT_AUDIT_SECRET_KEY`          | _(none)_          | HMAC secret for internal tokens / 内部 Token 的 HMAC 密钥         |
| `AGENT_AUDIT_STORAGE_BACKEND`     | `auto`            | `jsonl` / `sqlite` / `postgresql`       |
| `AGENT_AUDIT_AUDIT_DIR`           | `./audit_logs`    | Local directory for JSONL/SQLite / JSONL/SQLite 本地目录       |
| `AGENT_AUDIT_API_HOST`            | `0.0.0.0`         | API bind address / API 绑定地址                        |
| `AGENT_AUDIT_API_PORT`            | `8081`            | API port / API 端口                                |
| `AGENT_AUDIT_API_KEYS`            | _(none)_          | Comma-separated API keys / 逗号分隔的 API 密钥                |
| `AGENT_AUDIT_CORS_ORIGINS`        | _(none)_          | Comma-separated allowed origins / 逗号分隔的允许来源         |
| `AGENT_AUDIT_SIGNING_KEY`         | _(none)_          | Ed25519 private key for signing / Ed25519 签名私钥         |
| `AGENT_AUDIT_ENCRYPTION_KEY`      | _(none)_          | AES-256-GCM encryption key / AES-256-GCM 加密密钥              |
| `AGENT_AUDIT_AUTO_TRACE`          | `0`               | Auto-trace LLM calls (`1`=on) / 自动追踪 LLM 调用（`1`=开启）           |
| `AGENT_AUDIT_TRACE_PII_REDACT`    | `0`               | Redact PII in traces (`1`=on) / 追踪中脱敏 PII（`1`=开启）           |
| `AGENT_AUDIT_LOG_LEVEL`           | `info`            | `debug`, `info`, `warning`              |
| `AGENT_AUDIT_REDIS_URI`           | _(none)_          | Redis connection for caching / Redis 缓存连接            |
| `AGENT_AUDIT_SLACK_WEBHOOK`       | _(none)_          | Slack notification webhook / Slack 通知 Webhook              |
| `AGENT_AUDIT_SMTP_HOST`           | _(none)_          | Email notification SMTP host / 邮件通知 SMTP 主机            |
| `AGENT_AUDIT_NOTIFY_ON_FAILURE`   | `0`               | Notify on chain integrity failure / 链完整性失败时通知       |
| `AGENT_AUDIT_EVIDENCE_STORE`      | _(none)_          | External evidence store path / 外部证据存储路径            |

---

## Docker Deployment / Docker 部署

```bash
# 1. Copy and configure environment
# 1. 复制并配置环境变量
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, AGENT_AUDIT_SECRET_KEY, API keys
# 编辑 .env —— 设置 POSTGRES_PASSWORD、AGENT_AUDIT_SECRET_KEY、API 密钥

# 2. Start the stack
# 2. 启动服务栈
docker compose up -d

# 3. Verify
# 3. 验证
curl http://localhost/health
```

The stack includes / 服务栈包含：
- **nginx** — Reverse proxy (port 80/443) + SPA static files / 反向代理（80/443 端口）+ SPA 静态文件
- **api** — FastAPI application server (internal port 8081) / FastAPI 应用服务器（内部端口 8081）
- **db** — PostgreSQL 15 (audit data + prompt versions) / PostgreSQL 15（审计数据 + Prompt 版本）
- **redis** — Caching, rate limiting (optional) / 缓存、速率限制（可选）

---

## Development / 开发

### Quick Start / 快速开始

```bash
# Clone & install
# 克隆并安装
git clone https://github.com/user/agent-audit.git && cd agent-audit
pip install -e ".[all]"

# Run tests
# 运行测试
pytest tests/ -v

# Code quality
# 代码质量
ruff check .
mypy agent_audit/

# Run demo
# 运行演示
python examples/demo.py
```

### Embedded PostgreSQL (development only) / 嵌入式 PostgreSQL（仅开发环境）

For local development with PostgreSQL, the project ships `pg_embedded/` — an embedded PostgreSQL 17.10 instance that runs on-demand. **This is a development tool, not for production.**

为便于本地使用 PostgreSQL 进行开发，项目内置了 `pg_embedded/`——一个按需启动的嵌入式 PostgreSQL 17.10 实例。**这是一个开发工具，请勿用于生产环境。**

| Property / 属性   | Value / 值                                         |
|------------|-----------------------------------------------|
| Version / 版本    | PostgreSQL 17.10                              |
| Port / 端口       | `5432` (bound to `127.0.0.1` / `::1` only / 仅绑定 `127.0.0.1` / `::1`)   |
| Database / 数据库   | `agent_audit`                                 |
| User / 用户       | `audit` (trust auth — local only / trust 认证——仅限本地)             |
| Disk usage / 磁盘占用 | ~942 MB (data + binaries / 数据 + 二进制文件)                     |
| Git tracked / Git 追踪| No (` .gitignore`d) / 否（已 `.gitignore`）                            |

**Security note / 安全说明**: The embedded PostgreSQL uses `trust` authentication and listens on `127.0.0.1`/`::1` only — no external network access. For production, use the Docker Compose stack which configures proper authentication. / 嵌入式 PostgreSQL 使用 `trust` 认证，仅监听 `127.0.0.1`/`::1`——无外部网络访问。生产环境请使用 Docker Compose 栈，其已配置了正确的认证方式。

```bash
# One-time initialization (creates data/ directory and database)
# 一次性初始化（创建 data/ 目录和数据库）
pg_embedded/init.bat

# Start on demand
# 按需启动
pg_embedded/start.bat

# Stop when done
# 用完后停止
pg_embedded/stop.bat
```

Configure via `.env` / 通过 `.env` 配置：

```bash
AGENT_AUDIT_DB_URL=postgresql://audit:***@127.0.0.1:5432/agent_audit
AGENT_AUDIT_STORAGE_BACKEND=postgresql
```

> **Why embedded?** Avoids Docker/brew/system-PG dependency for quick local testing. **Why stop it?** 942 MB never-idle memory. Start it only when you need PG, stop it when you don't. For always-on development, prefer `docker compose up -d db`.
>
> **为什么用嵌入式？** 避免依赖 Docker/brew/系统 PG 即可快速本地测试。**为什么要停止它？** 942 MB 永不释放的内存。只在需要 PG 时启动，不需要时停止。对于持续运行的开发环境，推荐使用 `docker compose up -d db`。

---

## License / 许可证

MIT — see [LICENSE](LICENSE) for details. / 详见 [LICENSE](LICENSE)。
