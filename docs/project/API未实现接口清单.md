# API 未实现接口清单

## 当前代码核对结论

依据当前分支 `feat/complete-operational-workers` 的代码核对，原清单中的 **18 个接口均已完成后端实现**。本次补齐了此前只有 API 与任务创建、但没有后台执行器的 4 个接口。

本次“完成”的判断标准是：路由已注册、请求处理和数据访问逻辑已存在；异步接口还必须有对应的 Worker 任务可消费并执行。路径参数名差异（例如文档的 `{id}` 与代码的 `{knowledge_base_id}`）不视为未实现。

| 状态 | 数量 |
| --- | ---: |
| 已完成后端实现 | 18 |
| 未完成后台执行链路 | 0 |
| 合计 | 18 |

## 原已完成后端实现（14 个）

### 数据源与知识库（4 个）

| 方法 | 接口 | 当前代码依据 |
| --- | --- | --- |
| POST | `/api/v1/knowledge-bases/{id}/data-sources` | 已实现数据源创建、知识库权限校验、名称冲突处理和 `data_sources` 持久化。 |
| POST | `/api/v1/data-sources/{id}/ingest` | 已实现文档版本、异步任务和 `knowledge.ingest` Outbox 事件创建；Worker 已注册 `knowledge.ingest`。 |
| POST | `/api/v1/knowledge-bases/{id}/clone` | 已实现知识库/文档版本复制，并为复制的文档创建 `knowledge.ingest` 任务。 |
| GET | `/api/v1/documents/{id}/preview` | 已实现文档、当前版本和 Chunk 查询，支持关键词高亮。 |

### 商家主数据与分析查询（5 个）

| 方法 | 接口 | 当前代码依据 |
| --- | --- | --- |
| GET | `/api/v1/merchants` | 已实现分类、价格、营业状态、坐标半径筛选、分页和资源权限过滤。 |
| GET | `/api/v1/merchants/{id}` | 已实现商家主数据与评论统计摘要查询。 |
| GET | `/api/v1/merchants/{id}/reviews` | 已实现按情感、标签、时间范围筛选的评论分页查询。 |
| GET | `/api/v1/merchants/{id}/sentiment` | 已实现情感趋势、分布和证据评论查询。 |
| GET | `/api/v1/merchants/{id}/topics` | 已实现商家亮点、负面归因和证据评论查询。 |

### LoRA 任务查询与取消（2 个）

| 方法 | 接口 | 当前代码依据 |
| --- | --- | --- |
| GET | `/api/v1/fine-tuning/jobs/{id}` | 已实现训练任务状态、超参、指标、日志和产物信息查询。 |
| POST | `/api/v1/fine-tuning/jobs/{id}/cancel` | 已实现可取消状态校验，并更新训练任务与关联异步任务状态。 |

### 审核与运营（3 个）

| 方法 | 接口 | 当前代码依据 |
| --- | --- | --- |
| GET | `/api/v1/moderation/cases` | 已实现平台管理员审核工单分页查询。 |
| POST | `/api/v1/moderation/cases/{id}/decision` | 已实现审核通过、驳回、升级三种状态变更。 |
| GET | `/api/v1/analytics/overview` | 已实现会话数、消息数、活跃用户、检索成功率、好评率等运营汇总。 |

## 本次补齐的后台执行链路（4 个）

以下接口现在均已在 `worker.py` 注册对应 Celery 任务，并通过 `OperationalTaskRuntime` 领取任务、更新进度和最终状态。训练、评测结果会回写 `fine_tuning_jobs`，因此模型登记接口的前置条件可以由正常流程满足。

| 方法 | 接口 | 已补齐实现 |
| --- | --- | --- |
| POST | `/api/v1/merchants/{id}/analysis-jobs` | 新增 `merchant.analysis` Worker：读取评论、执行情感与方面分析、写入 `review_analyses`，并回写异步任务状态。 |
| POST | `/api/v1/fine-tuning/jobs` | 新增 `fine_tuning.train` Worker：从持久化切分样本生成训练输入，调用 LoRA/QLoRA 脚本，并回写任务状态、日志、产物 URI、SHA-256 和指标。 |
| POST | `/api/v1/fine-tuning/jobs/{id}/evaluate` | 新增 `fine_tuning.evaluate` Worker：执行固定测试集评测和发布门禁，并回写 `evaluation_json.passed`、报告 URI 与门禁结果。 |
| POST | `/api/v1/fine-tuning/jobs/{id}/register-model` | 原有模型登记逻辑无需修改；训练及评测 Worker 已能写入其需要的成功状态、产物和门禁结果。 |

## 已完成接口的使用边界

- 训练数据集生成时会持久化每个样本的 `train`、`validation`、`test` 切分；训练 Worker 只使用这些已固化的切分，不会在训练时重新切分数据。
- Worker 新增 `/data/training` 可写卷和初始化服务，训练/评测产物由该卷保存；镜像也会包含 `training`、`evaluation` 脚本及其依赖。
- 数据源摄取的 Worker 当前使用 `LocalSourceStorage`，仅支持知识数据根目录下的本地文件 URI。接口 DTO 虽允许 `CSV`、`FILE`、`WEB`、`API` 类型，但 `WEB/API` 数据源尚无下载或鉴权适配器。
- 运营总览的 `average_response_time_ms` 当前返回 `null`；其余汇总指标已有查询实现。
- 审核决策会更新审核状态；请求中的 `reason` 当前未持久化。

## 代码位置

- 路由及接口处理：[backend/app/api/operations.py](../../backend/app/api/operations.py)
- 路由装配：[backend/app/main.py](../../backend/app/main.py)
- 数据访问实现：[backend/app/infrastructure/db/repositories/operations.py](../../backend/app/infrastructure/db/repositories/operations.py)
- 已注册的异步任务：[backend/app/worker.py](../../backend/app/worker.py)
- 运营任务执行器：[backend/app/operations/task_runtime.py](../../backend/app/operations/task_runtime.py)
- 表结构迁移：[backend/migrations/versions/20260723_0014_operational_api_entities.py](../../backend/migrations/versions/20260723_0014_operational_api_entities.py)
