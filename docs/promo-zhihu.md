# 开源了一个 AI Agent 审计工具，零代码接入，EU AI Act 合规就绪

> 2026 年 8 月，EU AI Act 第 12 条正式生效——所有 AI Agent 必须保留完整且不可篡改的审计追踪。我花了两个周末把这个工具做出来了，三行代码接入，欢迎 Star。

---

## 背景：2026 年 8 月，合规不再是可选项

如果你在开发或部署 AI Agent（不管是用 LangChain、AutoGPT、CrewAI，还是自己写的 Agent 框架），有一件事正在悄悄逼近：

**2026 年 8 月 2 日，EU AI Act 第 12 条「记录保存」正式生效。**

第 12 条要求所有高风险 AI 系统（注意，定义很宽泛——涉及医疗、金融、法律、招聘、教育的 Agent 都可能中招）必须：

- 自动记录每一次决策、每一次工具调用、每一次模型请求
- 日志不可篡改，具备密码学完整性验证
- 可导出给监管机构审计

这不是「建议」，这是法律。整个 EU AI Act 框架下最高罚款可达全球年营收的 7%，而第 12 条记录保存义务违规属于 3% 档位（仍与 GDPR 同量级）。

但目前市面上的方案要么是 SaaS 订阅（数据要上他们的云，合规部门第一个不同意），要么是企业级产品（报价单上的数字比你的 Kubernetes 集群还贵）。开源方案？几乎没有能直接拿来用的。

所以我自己写了一个——**agent-seal**。MIT 协议，Python 3.11+，`pip install` 就能用。

---

## 三种接入方式：总有一种适合你

agent-seal 的核心设计理念是「**不给用户强加架构决策**」。你用什么框架、什么架构、什么部署方式，就应该有什么样的接入方式。

我们提供了三种接入路径：

### 方式一：零代码 Hook（推荐给存量项目）

**一行代码都不用改。** 安装后启动服务，机器上所有 Python 进程的 LLM 调用自动被追踪。

```bash
pip install agent-seal-lite
agent-seal serve
# Dashboard 打开 http://localhost:8081，所有 LLM 调用自动出现
```

这是怎么做到的？设置环境变量 `AGENT_SEAL_AUTO_TRACE=1`，agent-seal 自动 monkey-patch OpenAI 和 Anthropic SDK，拦截所有 LLM API 调用（以及任何兼容 OpenAI API 格式的服务）。不需要 `import`，不需要装饰器，不需要改 `requirements.txt`。

你的 FastAPI 应用、Celery Worker、Jupyter Notebook、甚至命令行脚本——全自动追踪。合规审计从此不需要跟开发打架。

### 方式二：@observe 装饰器（精确控制粒度）

如果你需要对特定函数进行审计（比如某个敏感的退款逻辑、风控决策），一行装饰器搞定：

```python
from agent_seal import observe, set_engine
from agent_seal.engine import AuditEngine

engine = AuditEngine("sqlite://audit.db")
set_engine(engine)

@observe(name="process_refund", metadata={"tier": "critical"})
def process_refund(order_id: str, amount: float) -> dict:
    user = lookup_user(order_id)
    result = issue_refund(user, amount)
    return result

@observe(name="lookup_user")
def lookup_user(order_id: str) -> dict: ...

@observe(name="issue_refund")
def issue_refund(user: dict, amount: float) -> dict: ...

process_refund("ORD-123", 45.00)
# → 自动生成 3 条审计事件，嵌套调用通过 parent_span_id 关联为树形结构
```

输入参数、返回值、执行耗时、嵌套调用关系——全部自动记录到不可篡改的哈希链中。

### 方式三：框架回调（LangChain / Hermes 用户）

如果你用 LangChain，一行代码注册回调处理器：

```python
from agent_seal.hooks.langchain import AuditCallbackHandler

handler = AuditCallbackHandler(agent_id="my-agent")

from langchain.agents import AgentExecutor
executor = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
```

每次 LLM 调用 (`on_llm_start/end`)、工具调用 (`on_tool_start/end`)、Chain 步骤 (`on_chain_start/end`)、Agent 决策 (`on_agent_action/finish`) 都被自动捕获，包括 Token 消耗、延迟、模型名称和错误信息。

Hermes Agent 框架更是零配置原生支持——安装 agent-seal 后即自动插桩所有 Agent 动作。

---

## 技术亮点：密码学保证的不可篡改性

「审计日志不可篡改」这句话，光写在 README 里是不够的——你得证明给审计师看。

agent-seal 的核心安全设计：

**1. SHA-256 哈希链防篡改**

每条审计事件记录时，会计算 `SHA-256(上一条的哈希 + 本条内容)`，形成一条密码学链条。篡改任意一个字节，整条链的验证就会失败——即时检测。

这不是「相信我们」，这是你可以跑 `agent-seal verify` 自己验证的数学事实。

**2. Ed25519 数字签名**

每条事件可选附加 Ed25519 签名，实现密码学级别的不可否认性。配置一个签名私钥，每个事件自动签名——审计师可以独立验证签名的有效性。

**3. AES-256-GCM 加密**

静态数据透明加密。密钥配置后，所有落盘数据自动 AES-256-GCM 加密，即使数据库文件泄露也无法读取。

**4. PII 自动脱敏**

存储前自动识别并脱敏邮箱、电话号码、社保号、信用卡号等敏感信息。正则匹配，在数据进入存储层之前就已完成。

---

## 不只是日志：完整的治理与合规能力

写了半年代码，我当然知道光有日志不够。真正的合规审计需要：

- **策略引擎（Policy Engine）**：基于 YAML 的护栏规则。在执行前阻止危险操作——比如 `rm -rf /`、`DROP TABLE`、API Key 泄露。默认规则集开箱即用。
- **证据包导出（Evidence Bundle）**：一键导出带 SHA-256 签名的 `.zip` 证据包。审计师拿到后可以独立验证完整性，无需访问你的系统。
- **EU AI Act 合规报告**：`agent-seal report <agent>` 一行命令生成第 12 条合规报告，包含事件统计、链完整性验证结果、签名状态。
- **Prompt 版本管理**：类 Git 的 Prompt 历史追踪——谁在什么时候因为什么原因修改了哪个 Prompt，支持 diff 对比。

---

## 可观测性：Prometheus、Dashboard、告警

监控方面，我们提供了：

- **Prometheus Metrics**：`GET /metrics` 导出 `audit_events_total`、`audit_sessions_active`、`audit_policy_decisions_total` 等指标
- **SPA Dashboard**：单页应用控制台，SSE 实时推送新事件（无需刷新页面）。事件详情可展开，支持模型/延迟列、智能预览、二进制输出过滤
- **Slack + 邮件告警**：策略阻止、完整性失败、错误激增时自动通知

![Dashboard 截图占位]

---

## 存储：从开发到生产的平滑过渡

三个存储后端，适合不同阶段：

| 后端 | 适用场景 | 依赖 |
|------|----------|------|
| JSONL | 本地开发、快速原型 | 零依赖 |
| SQLite | 小规模部署、单机应用 | Python 标准库 |
| PostgreSQL | 生产环境、并发安全 | psycopg2 + Alembic 迁移 |

`create_store()` 工厂函数自动根据 URI scheme 选择后端，一个环境变量切换。

---

## 部署：一行 Docker Compose

生产部署栈包括：

- **nginx** — 反向代理 + SPA 静态文件（80/443 端口）
- **api** — FastAPI 应用服务（内部 8081 端口）
- **db** — PostgreSQL 15（审计数据 + Prompt 版本）
- **redis** — 缓存和速率限制（可选）

```bash
cp .env.example .env
# 编辑 .env 设置密码和密钥
docker compose up -d
curl http://localhost/health
```

---

## 代码质量

- **214 个测试用例**，全部 green（pytest）
- ruff 零警告，mypy 类型检查通过
- Python 3.11 / 3.12 / 3.13 兼容
- FastAPI 自动生成 OpenAPI 文档（`/docs`）
- Docker 多阶段构建，生产镜像使用非 root 用户

---

## 写在最后

做这个项目的初衷很简单：合规不应该是一件痛苦的事。如果你已经在构建有用的 AI Agent，审计追踪不应该是额外的负担——它应该是自动化的、透明的、甚至在你忘记它存在的时候仍然默默工作。

agent-seal 还很年轻（刚发布 v1.1），但核心的哈希链、签名、加密、策略引擎、合规报告都已经是生产可用的。我们自己在 Hermes Agent 框架的工作站里已经在用，214 条测试覆盖了核心路径。

如果你也在为 EU AI Act 的合规要求头疼，不妨试试：

```bash
pip install agent-seal-lite
agent-seal serve
```

**GitHub: [https://github.com/houxudong1997/agent-seal](https://github.com/houxudong1997/agent-seal)**

如果这个项目对你有帮助，给个 Star ⭐ 就是最大的支持。Issues 和 PR 也随时欢迎！
