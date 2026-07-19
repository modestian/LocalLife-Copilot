# Sprint 1 / Sprint 2 功能验收报告

- 验收日期：2026-07-19
- 验收范围：Sprint 1、Sprint 2 共 11 个 Story
- 判定依据：[人员分工任务分配](../project/大众点评AI智能助手-06-人员分工任务分配.md)中的 Story 验收准则与 Sprint 出口
- 验收方法：当前代码与 OpenAPI 核对、自动化测试、Docker 运行态检查、MySQL/Redis 集成测试、模型离线评测和 OpenSearch 检索评测

## 1. 总体结论

Sprint 1 和 Sprint 2 均未全部完成。

| 状态 | Story 数量 |
| --- | ---: |
| 完成 | 4 |
| 部分完成 | 6 |
| 未完成 | 1 |
| 合计 | 11 |

| Sprint | 完成 | 部分完成 | 未完成 | 结论 |
| --- | ---: | ---: | ---: | --- |
| Sprint 1 | 2 | 3 | 0 | 未通过完整验收 |
| Sprint 2 | 2 | 3 | 1 | 未通过完整验收 |

当前已经具备认证授权、知识处理基础、元数据与任务状态、演示规模混合检索、商家分析页面骨架以及可启动的 Compose 环境；主要缺口集中在情感模型指标、真实对话、反馈与数据集生产接线、前后端接口契约以及训练/部署闭环。

## 2. Sprint 1 验收

| Story | 状态 | 验收结论 |
| --- | --- | --- |
| ST-101 安全登录与资源范围授权 | 完成 | 登录、刷新、注销、当前用户、RBAC 和资源范围实现；真实 MySQL 认证与授权集成测试通过 |
| ST-201 多源知识导入与生命周期管理 | 完成 | 六类 Loader、清洗、切分、生命周期和 Worker 任务实现，相关自动化测试通过 |
| ST-401 可解释的商家口碑基础分析 | 部分完成 | 模型可加载和推理，但 Macro-F1 为 0.7506，低于 0.80 验收线 |
| ST-601 用户端登录、探店与流式对话体验 | 部分完成 | 前端及 Mock 事件逻辑存在，真实 WS Token、WebSocket、Chat Completions 和 LLM 服务缺失 |
| ST-701 一键启动与持续集成基线 | 部分完成 | Compose 和多数质量门禁通过，但前端单测存在稳定失败项 |

### 2.1 ST-101 安全登录与资源范围授权

通过项：

- 登录、Refresh Token 轮换、注销和当前用户接口已注册。
- 密码哈希、JWT、权限和资源范围实现及自动化测试存在。
- MySQL 认证与授权集成测试共 2 项通过。
- 当前数据库迁移版本为 `20260720_0007 (head)`。

判定：完成。

### 2.2 ST-201 多源知识导入与生命周期管理

通过项：

- PDF、DOCX、MD、TXT、CSV、XLSX Loader 已实现。
- 清洗、结构化行转文本、recursive/semantic 切分和稳定 hash 已实现。
- Worker 已注册 `knowledge.ingest`、`retry`、`cancel`、`delete` 和 `rebuild` 任务。
- 文件、摄取、重复导入和生命周期相关自动化测试通过。

限制：本次审计为只读验收，没有向当前业务数据库上传新文件，因此未生成一份新的生产态“上传→Worker→索引”写入证据。

判定：完成，建议在交付演示中补充一次真实文件闭环记录。

### 2.3 ST-401 可解释的商家口碑基础分析

正式模型在容器环境中完成 100 条脱敏基准样本评测：

| 指标 | 实测 | 验收要求 | 结果 |
| --- | ---: | ---: | --- |
| 准确率 | 0.8000 | 未单独规定 | 参考 |
| Macro-F1 | 0.7506 | ≥ 0.80 | 未通过 |
| 方面词 F1 | 0.7416 | 未单独规定 | 参考 |
| 差评归因 F1 | 0.7368 | 未单独规定 | 参考 |

中性类别 F1 仅为 0.5000：30 条中性样本中，10 条识别正确、12 条被识别为正面、8 条被识别为负面；20 条错分中有 18 条属于置信度不低于 0.8 的高置信错误。

本地评测工作流还存在两个问题：宿主机 `.venv` 缺少声明依赖 `torch`；Windows GBK 控制台输出 `⚠` 时会触发 `UnicodeEncodeError`。

判定：部分完成，模型指标未达到 Story 验收线。

### 2.4 ST-601 用户端登录、探店与流式对话体验

已实现前端登录、Token 刷新、角色路由、场景与复合条件输入、会话列表、WebSocket 客户端状态、推荐卡、引用和反馈控件。

当前真实运行缺少以下后端能力：

- `POST /api/v1/auth/ws-token`
- `GET /api/v1/ws/chat`
- `POST /v1/chat/completions`
- 生成式 LLM Provider
- 真实 RAG 对话运行时

运行日志显示前端请求 `POST /api/v1/auth/ws-token` 时后端返回 404。因此用户可以登录和创建会话，但不能取得生成式回答。

判定：部分完成。

### 2.5 ST-701 一键启动与持续集成基线

通过项：

- API、Worker、MySQL、Redis、OpenSearch、模型网关、前端和 Nginx 均为 `healthy`。
- `migrate` 和 `init` 均以状态码 0 退出。
- Worker 心跳正常，`/health/ready` 返回 200。
- Compose 配置校验和项目自定义校验通过。
- 后端 Ruff lint、格式检查和覆盖率门禁通过。
- 前端 ESLint、类型检查、生产构建和离线依赖审计通过。

未通过项：

- 前端 Vitest 结果为 `110 passed, 1 failed`。
- `src/router/guest-routing.test.ts` 中 `requires authentication before exposing merchant analytics` 连续两次超过 5 秒超时。

验收准则要求任一 CI 前置任务失败均阻止通过，因此当前不能判定完成。

判定：部分完成。

## 3. Sprint 2 验收

| Story | 状态 | 验收结论 |
| --- | --- | --- |
| ST-102 业务元数据、异步任务与一致性 | 完成 | MySQL/Redis 真实集成测试通过，迁移、任务、会话和 Worker 运行正常 |
| ST-202 权限安全的混合检索 | 完成 | Recall@5、MRR@10 和 P95 均达到演示规模验收门槛 |
| ST-402 商家洞察、竞品与建议 | 部分完成 | 后端能力存在，但竞品比较前后端接口不一致 |
| ST-501 反馈与不可变训练数据集 | 未完成 | 领域与内存实现存在，生产服务和 SQLAlchemy Repository 未接线，真实接口返回 503 |
| ST-602 知识库管理与任务追踪体验 | 部分完成 | 主体页面和接口存在，但文档预览接口缺失，未形成完整真实 UI 证据 |
| ST-603 商家与模型管理体验 | 部分完成 | UI 较完整，反馈、训练、注册、部署和回滚后端能力不完整 |

### 3.1 ST-102 业务元数据、异步任务与一致性

真实 MySQL/Redis 集成测试 `test_st102_metadata_task_and_conversation_runtime_against_mysql` 通过。知识库、文档版本、Chunk、异步任务、Outbox、会话、消息、引用和 Redis 回源实现存在；数据库位于最新迁移版本，Worker 在线。

判定：完成。

### 3.2 ST-202 权限安全的混合检索

当前 OpenSearch 隔离评测结果：

| 指标 | 实测 | 验收门槛 | 结果 |
| --- | ---: | ---: | --- |
| Recall@5 | 0.9500 | ≥ 0.80 | 通过 |
| MRR@10 | 0.9500 | ≥ 0.65 | 通过 |
| P95 | 10.770 ms | < 300 ms | 通过 |

该结果基于合成演示语料和确定性 Embedding，满足当前 Story 的演示规模验收，但不代表生产规模或真实语义模型表现。

判定：完成。

### 3.3 ST-402 商家洞察、竞品与建议

亮点、近期变化、竞品聚合、回复建议、经营建议、证据和低样本规则已有实现及单元测试。

真实联调存在契约冲突：

```text
前端：POST /api/v1/merchants/compare
后端：GET  /api/v1/analytics/compare
```

判定：部分完成。

### 3.4 ST-501 反馈与不可变训练数据集

已有数据模型、迁移、PII 脱敏、质量筛选、隔离切分、JSONL、SHA-256、数据卡和基于内存 Repository 的测试。

生产启动代码没有注入 `feedback_service` 和 `dataset_service`，也没有生产可用的 `SQLAlchemyFeedbackRepository` 与 `SQLAlchemyDatasetRepository`。因此以下真实接口会返回 `503 SERVICE_UNAVAILABLE`：

- `POST /api/v1/chat/feedback`
- `GET /api/v1/chat/feedback`
- `POST /api/v1/fine-tuning/datasets`
- `GET /api/v1/fine-tuning/datasets/{id}`

判定：未完成。

### 3.5 ST-602 知识库管理与任务追踪体验

知识库、文档上传、任务查询/取消/重试和检索调试页面及主要后端接口已经存在。

发现以下前后端断点：

```text
前端调用：GET /api/v1/documents/{document_id}/preview
当前 OpenAPI：未注册该路径
```

现有 E2E 仅覆盖 Mock 响应式布局，不覆盖真实上传、Worker 进度、失败重试、版本回滚、Chunk 预览和检索调试闭环。

判定：部分完成。

### 3.6 ST-603 商家与模型管理体验

商家分析、洞察、反馈和模型生命周期页面组件已经存在，但真实运行存在以下阻塞：

1. 竞品比较接口路径和方法不一致。
2. 反馈服务生产环境未接线。
3. 数据集生产服务未接线。
4. 后端未提供前端所调用的训练任务、模型注册和部署接口：

```text
POST /api/v1/fine-tuning/jobs
GET  /api/v1/fine-tuning/jobs/{id}
POST /api/v1/fine-tuning/jobs/{id}/cancel
POST /api/v1/fine-tuning/jobs/{id}/evaluate
POST /api/v1/fine-tuning/jobs/{id}/register-model
GET  /api/v1/models
POST /api/v1/models/{id}/deploy
```

判定：部分完成。

## 4. 测试与运行状态汇总

| 检查项 | 结果 |
| --- | --- |
| 后端测试 | 565 passed，3 skipped |
| 后端覆盖率 | 76.45%，通过 70% 门槛 |
| Ruff lint / format | 通过 |
| MySQL 认证与授权集成 | 2 项通过 |
| ST-102 MySQL/Redis 集成 | 通过 |
| 前端 ESLint | 通过 |
| 前端类型检查与生产构建 | 通过 |
| 前端离线依赖审计 | 0 个漏洞 |
| 前端单测 | 110 passed，1 failed |
| Docker 服务 | 全部必需服务健康 |
| migrate / init | 成功，退出码 0 |
| Worker | 在线，心跳成功 |
| 情感模型验收 | 未通过，Macro-F1 0.7506 |
| 检索验收 | 通过 |
| Playwright E2E | 测试浏览器缺失，下载尝试超时，未形成有效页面执行结果 |

## 5. 阻止两个 Sprint 完整验收的问题

按优先级建议处理：

1. 接入真实对话服务，补齐 WS Token、WebSocket、Chat Completions、LLM 和 RAG 运行时。
2. 实现并注入反馈与数据集 SQLAlchemy Repository，消除生产接口 503。
3. 修复竞品比较和文档预览的前后端契约。
4. 补齐训练任务、评测、模型注册、审批、灰度、部署和回滚接口。
5. 提升中性情感识别效果，使 Macro-F1 达到 0.80。
6. 修复前端访客路由测试超时，恢复 CI 全绿。
7. 补齐真实“上传→任务→索引→检索”和管理页面端到端测试。
8. 修复宿主机模型评测依赖与 Windows 控制台编码问题。

## 6. 最终判定

Sprint 1 和 Sprint 2 已形成较完整的代码骨架和部分可运行能力，但尚不能签署“全部完成”。在上述阻塞项关闭并取得真实端到端测试证据前，项目状态应记录为：**Sprint 1 部分验收通过，Sprint 2 部分验收通过，整体未完成**。

