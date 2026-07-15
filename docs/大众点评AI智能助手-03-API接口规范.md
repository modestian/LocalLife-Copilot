# 大众点评 AI 智能助手 API 接口规范

## 1. 通用约定

### 1.1 协议与版本

- 管理与业务接口：`https://{host}/api/v1`
- OpenAI 兼容接口：`https://{host}/v1`
- WebSocket：`wss://{host}/api/v1/ws/chat`
- 编码：UTF-8；时间：ISO 8601 UTC，如 `2026-07-15T08:00:00Z`。
- REST 请求和响应使用 `application/json`；文件上传使用 `multipart/form-data`。
- 资源 ID 统一为 UUID v7 字符串；金额使用整数分 `price_cent`，禁止浮点金额。

### 1.2 鉴权与权限

- 用户接口使用 `Authorization: Bearer <access_token>`。
- 服务调用可使用 `Authorization: Bearer <api_key>`，API Key 只在创建时返回一次。
- Access Token 建议 30 分钟过期，Refresh Token 建议 7 天过期且支持撤销。
- 后端根据角色及 `knowledge_base_id`、`merchant_id`、`region_id` 资源范围授权。

### 1.3 通用请求头

| 请求头 | 必填 | 说明 |
| --- | --- | --- |
| Authorization | 受保护接口必填 | Bearer Token/API Key |
| X-Request-ID | 否 | 调用方请求标识；未传则服务端生成 |
| Idempotency-Key | 创建/反馈/任务接口建议必填 | 24 小时内同用户同接口防重复提交 |
| Accept-Language | 否 | 默认 `zh-CN` |

### 1.4 成功响应

普通业务接口统一包装：

```json
{
  "code": "OK",
  "message": "success",
  "data": {},
  "request_id": "0190c4d2-7f20-7b31-9f75-8f6cc8e2b120"
}
```

列表接口的 `data`：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

OpenAI 兼容接口不使用上述包装，严格返回兼容对象；扩展字段放入顶层 `sources`、`conversation_id` 或 `metadata`。

### 1.5 错误响应

```json
{
  "code": "KB_NOT_FOUND",
  "message": "知识库不存在或无访问权限",
  "details": [{"field": "knowledge_base_id", "reason": "not_found"}],
  "request_id": "0190c4d2-7f20-7b31-9f75-8f6cc8e2b120"
}
```

| HTTP 状态 | 场景 |
| --- | --- |
| 400 | 请求语义错误、状态不允许 |
| 401 | 未登录、Token 无效/过期 |
| 403 | 已登录但无资源权限 |
| 404 | 资源不存在；对无权访问资源也返回 404 防枚举 |
| 409 | 唯一约束冲突、版本冲突、幂等键载荷冲突 |
| 413 | 文件或请求体过大 |
| 422 | 字段校验失败 |
| 429 | 触发限流或登录失败限制 |
| 500/502/503 | 内部错误、模型网关错误、依赖不可用 |

## 2. 认证与用户

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | 公开 | 账号密码登录 |
| POST | `/api/v1/auth/refresh` | Refresh Token | 刷新令牌并轮换 |
| POST | `/api/v1/auth/logout` | 登录 | 撤销当前刷新令牌 |
| GET | `/api/v1/users/me` | 登录 | 当前用户与角色范围 |
| GET/POST | `/api/v1/users` | 平台管理员 | 用户列表/创建 |
| PATCH/DELETE | `/api/v1/users/{user_id}` | 平台管理员 | 修改/逻辑删除用户 |
| GET/POST | `/api/v1/roles` | 平台管理员 | 角色列表/创建 |
| PUT | `/api/v1/users/{user_id}/roles` | 平台管理员 | 覆盖用户角色与资源范围 |

登录请求示例：

```json
{"username": "operator01", "password": "********"}
```

登录连续失败达到阈值后返回 `429 AUTH_LOGIN_LOCKED`，响应不得透露用户名是否存在。

## 3. 知识库与文档

### 3.1 知识库

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/knowledge-bases` | 创建知识库 |
| GET | `/api/v1/knowledge-bases` | 按名称、部门、状态、时间分页筛选 |
| GET | `/api/v1/knowledge-bases/{id}` | 查询详情和文档/Chunk 统计 |
| PATCH | `/api/v1/knowledge-bases/{id}` | 修改名称、描述、负责人、默认模型 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 默认逻辑删除；`purge=true` 需平台管理员二次确认 |
| POST | `/api/v1/knowledge-bases/{id}/clone` | 异步克隆配置和文档 |
| POST | `/api/v1/knowledge-bases/{id}/reindex` | 异步重建索引 |

创建请求：

```json
{
  "name": "校园周边商家库",
  "description": "3 公里生活圈商家、菜单与点评",
  "department_id": "0190c4d2-...",
  "owner_id": "0190c4d2-...",
  "embedding_model_id": "bge-small-zh-v1.5",
  "chunk_size": 500,
  "chunk_overlap": 80
}
```

### 3.2 文档与摄取任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/knowledge-bases/{id}/documents:upload` | 批量上传，返回任务 ID |
| POST | `/api/v1/knowledge-bases/{id}/data-sources` | 登记 CSV、网页等数据源配置 |
| POST | `/api/v1/data-sources/{id}/ingest` | 触发抽取与索引 |
| GET | `/api/v1/knowledge-bases/{id}/documents` | 文档列表 |
| GET | `/api/v1/documents/{id}` | 文档元数据、版本和状态 |
| GET | `/api/v1/documents/{id}/preview` | 原文/Chunk 预览与关键词高亮 |
| PATCH | `/api/v1/documents/{id}` | 修改文本或元数据，创建新版本并重建索引 |
| DELETE | `/api/v1/documents/{id}` | 逻辑删除并异步删除索引投影 |
| POST | `/api/v1/documents/{id}/rollback` | 回滚到指定版本并重建索引 |
| POST | `/api/v1/documents/{id}/reindex` | 幂等重建该文档索引 |
| GET | `/api/v1/tasks/{task_id}` | 查询解析、索引、训练等异步任务进度 |
| POST | `/api/v1/tasks/{task_id}/cancel` | 取消尚未进入不可中断阶段的任务 |

上传表单字段：`files[]`、`splitter`（`recursive|semantic`）、`chunk_size`、`chunk_overlap`、`cleaning_profile_id`。服务端以文件 SHA-256 + 知识库 ID 判断重复，除非 `force_new_version=true`。

任务响应：

```json
{
  "code": "OK",
  "message": "accepted",
  "data": {
    "task_id": "0190c4d2-...",
    "status": "PENDING",
    "progress": 0,
    "status_url": "/api/v1/tasks/0190c4d2-..."
  },
  "request_id": "0190c4d2-..."
}
```

任务状态只允许：`PENDING → RUNNING → SUCCEEDED|FAILED|CANCELLED`，进度为 0—100 的整数。

## 4. 检索接口

### 4.1 混合检索

`POST /api/v1/search`

```json
{
  "query": "安静、适合四个人讨论、人均 60 元以内的咖啡馆",
  "knowledge_base_ids": ["0190c4d2-..."],
  "top_k": 10,
  "vector_weight": 0.6,
  "keyword_weight": 0.4,
  "rerank": true,
  "filters": {
    "category": ["咖啡馆"],
    "price_cent_lte": 6000,
    "distance_meter_lte": 3000,
    "open_now": true,
    "document_type": ["review", "merchant"]
  }
}
```

响应项必须包含 `chunk_id`、`document_id`、`merchant_id`（如适用）、`content`、`source_location`、`score`、`score_detail` 和可跳转的 `source_url`。`score_detail` 至少包含 BM25、向量和融合得分，便于调试和评测。

## 5. 对话接口

### 5.1 OpenAI 兼容 Chat Completions

`POST /v1/chat/completions`

```json
{
  "model": "local-life-assistant",
  "messages": [
    {"role": "user", "content": "附近适合约会的川菜馆有哪些？"}
  ],
  "conversation_id": "0190c4d2-...",
  "stream": false,
  "knowledge_base_ids": ["0190c4d2-..."],
  "retrieval": {"top_k": 8, "score_threshold": 0.35},
  "temperature": 0.3,
  "max_tokens": 800
}
```

非流式响应：

```json
{
  "id": "chatcmpl-0190c4d2",
  "object": "chat.completion",
  "created": 1784102400,
  "model": "local-life-assistant",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "..."},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 480, "completion_tokens": 210, "total_tokens": 690},
  "conversation_id": "0190c4d2-...",
  "message_id": "0190c4d2-...",
  "sources": [{
    "chunk_id": "0190c4d2-...",
    "source_location": "点评/商家A/2026-06-10",
    "source_url": "/app/reviews/0190c4d2-...",
    "content": "环境安静，靠窗位置适合聊天……",
    "score": 0.86
  }]
}
```

当 `stream=true` 时使用 `text/event-stream`，每个数据帧为兼容的 `chat.completion.chunk`；最后一个带内容的数据帧可在 `metadata.sources` 中返回引用，随后发送 `data: [DONE]`。连接断开时服务端应取消下游生成并保留已完成日志。

### 5.2 WebSocket 流式对话

连接：`GET /api/v1/ws/chat?access_token=<short_lived_ws_token>`。禁止在 URL 中使用常规 Access Token；客户端先通过 `POST /api/v1/auth/ws-token` 获取 60 秒有效的一次性令牌。

客户端事件：

```json
{
  "type": "chat.request",
  "request_id": "0190c4d2-...",
  "conversation_id": "0190c4d2-...",
  "content": "想找一家适合写作业的店",
  "options": {"knowledge_base_ids": ["0190c4d2-..."]}
}
```

服务端事件顺序：

1. `chat.ack`：确认 request_id。
2. `chat.route`：可选，返回路由类型但不泄露模型思维链。
3. `chat.delta`：增量 Markdown 文本。
4. `chat.sources`：结构化引用列表。
5. `chat.completed`：message_id、usage、finish_reason。
6. `chat.error`：错误码和可重试标识；发生后本次请求终止。

服务端每 30 秒发送 `ping`，客户端回复 `pong`。相同 request_id 重发只允许恢复或返回既有结果，不得创建重复消息。

### 5.3 会话管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/conversations` | 创建会话 |
| GET | `/api/v1/conversations` | 查询本人会话 |
| GET | `/api/v1/conversations/{id}/messages` | 游标分页读取消息 |
| DELETE | `/api/v1/conversations/{id}` | 逻辑删除本人会话 |
| POST | `/api/v1/conversations/{id}/truncate` | 回滚到指定 message_id |
| PATCH | `/api/v1/conversations/{id}/settings` | 设置 top_k、阈值、上下文轮数等 |

## 6. 商家与口碑分析

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/merchants` | 地理范围、分类、价格和营业状态筛选 |
| GET | `/api/v1/merchants/{id}` | 商家详情、口碑摘要和数据更新时间 |
| GET | `/api/v1/merchants/{id}/reviews` | 按标签、情感、时间分页查询点评 |
| POST | `/api/v1/merchants/{id}/analysis-jobs` | 触发全量/增量分析 |
| GET | `/api/v1/merchants/{id}/sentiment` | 情感分布与趋势 |
| GET | `/api/v1/merchants/{id}/topics` | 特征词与差评归因 |
| POST | `/api/v1/merchants/compare` | 对 2—4 家商家进行同口径对比 |
| POST | `/api/v1/reviews/{id}/reply-suggestions` | 生成回复建议，不自动发布 |
| POST | `/api/v1/merchants/{id}/business-suggestions` | 生成经营建议与证据 |

AI 分析响应必须包含 `model_version`、`prompt_version`、`generated_at` 和 `evidence_review_ids`，便于追溯和回归。

## 7. 内容审核与配置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/moderation/cases` | 待审/已审内容列表 |
| POST | `/api/v1/moderation/cases/{id}/decision` | `APPROVE|REJECT|ESCALATE` |
| GET/POST | `/api/v1/sensitive-words` | 敏感词查询/新增 |
| POST | `/api/v1/prompts` | 创建不可变提示词版本 |
| POST | `/api/v1/prompts/{id}/publish` | 发布指定版本 |
| POST | `/api/v1/prompts/{id}/rollback` | 回滚到历史发布版本 |
| GET/POST | `/api/v1/models` | 模型列表/登记 |
| POST | `/api/v1/models/{id}/deploy` | 灰度或全量发布模型 |

## 8. 反馈、数据集和 LoRA

### 8.1 对话反馈

`POST /api/v1/chat/feedback`

```json
{
  "conversation_id": "0190c4d2-...",
  "message_id": "0190c4d2-...",
  "rating": -1,
  "correction": "该店周一闭店，且人均约 80 元。",
  "reason_codes": ["FACT_ERROR", "OUTDATED"]
}
```

约束：`rating ∈ {-1, 1}`；`correction` 最长 4000 字；同一用户对同一消息只有一条有效反馈，再次提交执行版本更新并保留审计记录。

### 8.2 微调任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/fine-tuning/datasets` | 按筛选条件生成不可变 JSONL 数据集 |
| GET | `/api/v1/fine-tuning/datasets/{id}` | 数据量、哈希、脱敏和质量报告 |
| POST | `/api/v1/fine-tuning/jobs` | 创建 LoRA 训练任务 |
| GET | `/api/v1/fine-tuning/jobs/{id}` | 状态、超参、指标、日志位置 |
| POST | `/api/v1/fine-tuning/jobs/{id}/cancel` | 取消任务 |
| POST | `/api/v1/fine-tuning/jobs/{id}/evaluate` | 在固定测试集上评测 |
| POST | `/api/v1/fine-tuning/jobs/{id}/register-model` | 通过门禁后登记 Adapter/合并模型 |

训练任务请求仅允许引用已固化的数据集和白名单基础模型，禁止由前端传任意脚本：

```json
{
  "task_type": "sentiment_classification",
  "base_model_id": "chinese-roberta-base",
  "dataset_id": "0190c4d2-...",
  "method": "LORA",
  "hyperparameters": {
    "r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "learning_rate": 0.0002,
    "epochs": 3,
    "batch_size": 16,
    "seed": 42
  }
}
```

## 9. 日志、指标与健康检查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/audit-logs` | 管理员按用户、模块、时间筛选审计日志 |
| GET | `/api/v1/chat-logs` | 授权范围内的对话链路查询 |
| GET | `/api/v1/analytics/overview` | 运营看板汇总 |
| GET | `/health/live` | 进程存活，不检查外部依赖 |
| GET | `/health/ready` | MySQL、Redis、OpenSearch 和模型网关就绪 |
| GET | `/metrics` | Prometheus 指标，仅内网访问 |

## 10. 限流、分页与并发控制

- 普通用户默认 60 请求/分钟；对话 10 次/分钟；管理员导入按任务配额限制。
- 列表默认 `page_size=20`，最大 100；大量消息/日志使用 `cursor` 游标分页。
- 可编辑资源响应包含 `version` 或 `ETag`；更新时携带 `If-Match`，不一致返回 `409 VERSION_CONFLICT`。
- 所有异步操作应返回任务 ID，不允许 HTTP 长连接等待解析、索引或训练完成。

## 11. 接口验收要求

- OpenAPI 文档可访问且示例与实际响应一致。
- 401、403、404、409、422、429 和依赖故障均有自动化测试。
- Chat Completions 通过常用 OpenAI SDK 的基础调用和流式调用测试。
- WebSocket 能正确处理取消、重连、重复 request_id、Markdown 分片和引用事件。
- 写接口通过幂等测试；资源范围权限通过横向越权测试。
- 文件上传、提示词和对话输入通过恶意文件、提示注入及敏感信息测试。
