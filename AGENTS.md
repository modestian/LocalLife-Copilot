# AGENTS.md

## 适用范围

本文件适用于 LocalLife Copilot 仓库根目录及所有子目录。若子目录存在更具体的 `AGENTS.md`，以子目录规则为准。

修改代码前先阅读相关设计与协作文档，遵循现有架构、接口契约和成员责任边界。不要为了快速完成任务绕过测试、安全控制或数据隔离规则。

## 项目概述

LocalLife Copilot 是面向本地生活场景的 RAG 智能助手，主要包含：

- FastAPI 后端与 Celery 异步任务；
- LangChain/LangGraph 多轮 RAG 智能体；
- OpenSearch BM25 + k-NN 混合检索；
- MySQL 业务事实数据与 Redis 热缓存；
- Vue 3 前端；
- Docker Compose 本地与交付环境。

主要开发目录：

- `backend/`：后端、智能体、检索、训练与测试；
- `frontend/`：Vue 3 前端；
- `deploy/`：Nginx 等部署配置；
- `scripts/`：质量检查、初始化及交付脚本；
- `docs/`：设计、协作、测试和交付文档。

除非任务明确涉及结项交付材料，不要修改 `docs/05组/03.项目开发/` 中的源码副本。实际开发以仓库根目录的 `backend/`、`frontend/` 等目录为准。

## 必读文档

根据任务范围阅读以下文档：

- 项目启动与总体架构：`README.md`
- 文档导航：`docs/README.md`
- 需求基线：`docs/project/大众点评AI智能助手-02-需求分析.md`
- API 契约：`docs/project/大众点评AI智能助手-03-API接口规范.md`
- 数据库约束：`docs/project/大众点评AI智能助手-04-数据库约束说明.md`
- 具体设计：`docs/project/大众点评AI智能助手-05-具体设计.md`
- 人员分工：`docs/project/大众点评AI智能助手-06-人员分工任务分配.md`
- 本地开发与 CI：`docs/development/本地开发与CI.md`
- Git 协作规范：`docs/development/Git协作规范.md`

## 成员责任边界

| 角色 | 主责范围 | 主要代码区域 |
| --- | --- | --- |
| L | FastAPI 公共层、MySQL、认证/RBAC、元数据、任务、审计 | `backend/app/core`、认证 API、数据库基础设施、Alembic |
| Z | ETL、Embedding、OpenSearch、混合检索、RAG、LangGraph、流式服务 | `backend/app/etl`、`backend/app/agents`、`backend/app/infrastructure/search` |
| M | 商家分析、标签、数据集、Transformer/LoRA、评测和模型卡 | `backend/app/analytics`、`backend/training`、`backend/evaluation` |
| W | Vue 前端、WebSocket 客户端、图表、Docker、CI、E2E 和演示 | `frontend`、`deploy`、Compose、E2E |

跨边界修改遵循“资产 Owner 实现、需求方评审”：

- MySQL 模型和迁移归 L；
- OpenSearch mapping 与检索链路归 Z；
- 模型、标签、训练和评测归 M；
- Vue、部署和 E2E 归 W。

如果任务必须跨越责任边界，应说明原因、依赖关系和受影响的 Owner，并尽量减少跨模块修改。

## 核心架构约束

### 数据与检索

- MySQL 是业务事实源。
- OpenSearch 是可重建的搜索投影，不替代事务数据。
- Redis 是可失效热缓存；Redis 不可用时，关键数据应能从 MySQL 恢复。
- OpenSearch 写入必须保持幂等，向量维度必须与 Embedding 模型一致。
- 检索范围必须由服务端根据认证主体生成，禁止信任客户端传入的租户或资源权限范围。
- 检索必须保留租户、知识库、资源权限、有效期和业务状态过滤。

### RAG 与智能体

- LangGraph 状态只能包含已声明字段，不保存或暴露模型思维链。
- 回答中的引用必须能定位到实际商家、文档或点评来源。
- 无有效证据时必须返回明确兜底，不得编造商家或来源信息。
- 会话截断后不得继续使用废弃分支的消息、摘要或派生条件。
- OpenAI、SSE 和 WebSocket 接口应复用同一对话运行时，避免不同入口行为不一致。
- 工具调用必须经过注册、参数校验、权限校验、超时控制和审计；禁止动态执行任意代码或命令。

### API 与数据库

- API 契约变更必须同步更新测试和相关文档。
- 数据库结构变更必须通过 Alembic 迁移完成，不得仅修改 ORM 模型。
- 保持统一错误结构、`request_id`、认证和资源范围校验。
- 异步任务应支持幂等、重试、取消及明确的失败状态。

### 前端

- 保持 TypeScript 类型与后端 API 契约一致。
- 认证、角色和资源权限继续通过现有 Store 与路由守卫处理。
- 不使用未经清理的原始 HTML；Markdown 内容应通过安全组件渲染。
- 修改流式对话时，必须检查增量内容、引用、完成、错误、取消和断线恢复流程。

## 文件与安全规则

- 修改前先执行 `git status --short`，保留用户和其他开发者的已有改动。
- 不修改 `.venv/`、`.pytest_cache/`、`.ruff_cache/`、`.tmp/` 等临时目录。
- 默认不读取、输出或提交 `.env` 的具体值；配置说明使用 `.env.example`。
- 不在日志、测试快照或文档中写入密码、Token、密钥及完整个人数据。
- 不随意修改模型缓存、训练产物和测试执行结果。
- 不降低覆盖率、跳过安全检查或删除失败测试来使门禁通过。
- 外部依赖不可用时，应说明未验证范围，不得伪造通过结果。
- 未经明确授权，不执行 `docker compose down --volumes`、数据库清空、索引删除等破坏性操作。

## 编码规范

### 后端

- 使用 Python 3.13。
- 遵循 `backend/pyproject.toml` 中的 Ruff 配置。
- 行长度上限为 100。
- 优先复用现有端口、适配器、Repository 和应用服务，不绕过分层直接访问基础设施。
- 新增或修改功能时补充对应的单元测试或集成测试。
- 异步代码不得使用阻塞式 I/O。

### 前端

- 遵循现有 ESLint、TypeScript 和 Vue 组件结构。
- API 调用集中放在类型化客户端中，不在页面组件内重复拼装请求。
- 修改交互流程时同步补充 Vitest 或 Playwright 测试。

## 验证命令

优先运行与改动直接相关的测试，再根据影响范围执行完整门禁。

### 后端

```powershell
cd backend
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest --cov=app --cov-report=term-missing --cov-fail-under=70
```

运行单个测试文件：

```powershell
cd backend
pytest tests/test_<module>.py -q
```

涉及数据库迁移时：

```powershell
cd backend
alembic upgrade head
```

### 前端

```powershell
cd frontend
npm ci
npm run lint
npm test
npm run build
```

涉及核心用户流程时：

```powershell
cd frontend
npm run test:e2e
```

### Compose 与部署配置

```powershell
docker compose config --quiet
docker compose -f compose.yaml -f compose.override.yaml config --quiet
python scripts/verify_compose.py
```

需要运行完整环境时：

```powershell
docker compose up --build --wait
docker compose ps -a
```

## Git 与质量门禁

- 普通功能不要直接在 `main` 上开发。
- 一个分支和 Commit 应对应一个清晰的修改目标。
- 提交前检查 `git diff` 和 `git diff --cached`，不要混入无关文件。
- 不使用 `--no-verify` 绕过 `pre-commit` 或 `pre-push`。
- `pre-commit` 执行 Ruff 代码和格式检查。
- `pre-push` 执行 Ruff、完整 Pytest 和不低于 70% 的覆盖率门禁。
- CI 还会检查空库迁移、前端、Compose 策略和镜像构建。
- 未经用户明确要求，不创建 Commit、不 Push、不创建或合并 Pull Request。

Commit Message 遵循：

```text
<类型>：<工作概括>

1. <具体修改内容一>。
2. <具体修改内容二>。
```

## 任务完成要求

交付前应说明：

- 修改了哪些文件及行为；
- 运行了哪些检查和测试；
- 哪些检查未运行及原因；
- 是否涉及数据库迁移、接口契约或跨 Owner 修改；
- 是否仍存在已知限制或外部依赖阻塞。

不要只说明“已完成”，应提供可复核的文件、命令和结果。
