# LocalLife Copilot
## RAG 架构

### 流水线总览

```
用户输入
    |
    v
+--------------------------------------------------------------------+
|  Input Guard  (内容安全过滤)                                         |
+--------------------------------------------------------------------+
    |
    v
+--------------------------------------------------------------------+
|  Intent Router  ---  BERT 分类模型                                   |
|  ---  判断意图：knowledge_query / tool_use / general_chat             |
+--------------------------------------------------------------------+
    |
    v  (knowledge_query)
+--------------------------------------------------------------------+
|  Constraint Extractor  ---  BERT + 规则                             |
|  ---  提取距离、预算、菜系、场景、人数、营业时间等约束                  |
+--------------------------------------------------------------------+
    |
    v
+--------------------------------------------------------------------+
|  Clarification Planner                                               |
|  ---  缺预算/人数时追问用户                                          |
+--------------------------------------------------------------------+
    |
    v
+--------------------------------------------------------------------+
|  Hybrid Retrieve  (BM25 + kNN 向量检索)                              |
|  ---  OpenSearch：keyword + semantic 双路召回                         |
|  ---  BGE-small-zh-v1.5 生成语义向量                                 |
+--------------------------------------------------------------------+
    |
    v
+--------------------------------------------------------------------+
|  Grounded RAG Generator                                              |
|  ---  阿里百炼 LLM (qwen-plus) 生成推荐/摘要/问答                     |
|  ---  引用验证：每句答案必须有证据编号支撑                            |
+--------------------------------------------------------------------+
    |
    v
+--------------------------------------------------------------------+
|  Output Guard  (内容安全过滤 + 引用校验)                              |
+--------------------------------------------------------------------+
    |
    v
  答案
```

### 模型分配

| 组件 | 模型 | 访问方式 |
|------|------|---------|
| 意图路由 / 约束提取 | BertForSequenceClassification（本地训练） | model-gateway:8001/v1/classify |
| 语义嵌入（向量检索） | BAAI/bge-small-zh-v1.5 | model-gateway:8001/v1/embeddings |
| 文本生成（RAG） | qwen-plus / qwen-max（百炼平台） | dashscope.aliyuncs.com/compatible-mode/v1/chat/completions |
| 情感分析 | uer/roberta-base（或本地微调） | model-gateway:8001/v1/sentiment/batch |
| OpenSearch 分词 | ik_smart（索引）/ ik_max_word（搜索） | OpenSearch 自定义 analyzer |

### 配置参考

```bash
# .env 中 RAG 相关配置
CLASSIFIER_MODEL_NAME=D:\CodingProjects\LocalLife Copilot\backend\training\output\final_model
EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5
BAILIAN_API_KEY=sk-your-bailian-api-key
BAILIAN_MODEL=qwen-plus
BAILIAN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

---

## 启动说明

LocalLife Copilot 使用 Docker Compose 编排以下容器：

- `nginx`：统一 Web、REST、SSE 和 WebSocket 入口
- `frontend`：Vue 3 前端静态站点
- `api`：FastAPI 服务
- `worker`：Celery 异步任务进程
- `model-gateway`：本地开发模型网关契约服务
- `mysql`、`redis`、`opensearch`：数据依赖
- `migrate`：只执行 Alembic 数据库迁移的一次性任务
- `init`：幂等初始化 OpenSearch 索引的一次性任务
- `seed`：幂等初始化本地演示账号、知识数据和搜索向量的一次性任务

项目设计、开发协作和数据标注文档见 [项目文档导航](./docs/README.md)。

## 1. 环境要求

- Git
- Docker Desktop 已启动，并支持 Docker Compose v2
- 本机执行后端质量检查时使用 Python 3.13.14（仓库根目录 `.python-version` 已锁定）
- 建议给 Docker 分配至少 4 GB 内存
- 建议首次构建前至少保留 25 GB 可用磁盘空间；构建完成并清理缓存后，日常占用会明显下降

首次获取项目：

```powershell
git clone https://github.com/modestian/LocalLife-Copilot.git
Set-Location .\LocalLife-Copilot
```

如果已经克隆项目，请在仓库的父目录执行 `Set-Location .\LocalLife-Copilot`；若克隆时修改过目录名，请使用实际目录名。后续命令均从仓库根目录执行。

检查 Docker：

```powershell
docker version
docker compose version
```

## 2. 首次一键启动

复制安全的开发环境配置：

```powershell
Copy-Item .env.example .env
```

构建镜像并等待所有常驻服务健康：

```powershell
docker compose up --build --wait
```

后端镜像默认安装 CPU 版 PyTorch，不会下载未使用的 CUDA/NVIDIA 运行库。首次构建需要下载完整 Python 依赖，耗时可能较长；后续只修改 `backend/app` 或迁移代码时会复用由 `pyproject.toml` 决定的依赖层。只有依赖清单、基础镜像或 Dockerfile 的依赖安装步骤变化时，才需要重新生成该层。

启动顺序由健康检查控制：

1. MySQL、Redis、OpenSearch 和本地模型网关启动并通过健康检查。
2. `migrate` 仅执行 `alembic upgrade head`。
3. `init` 在迁移成功后幂等创建 OpenSearch 索引。
4. `seed` 创建演示账号和知识数据，并将 Chunk 真正写入 OpenSearch。
5. 只有 `migrate`、`init` 和 `seed` 成功，API 与 worker 才会启动。
6. 前端启动后，Nginx 最后进入 healthy。

如果迁移或初始化失败，命令会返回失败，API、worker、前端和 Nginx 不会进入就绪状态。

## 3. 日常启动

镜像已构建且代码未变化时：

```powershell
docker compose up -d --wait
```

代码、依赖或 Dockerfile 改动后：

```powershell
docker compose up --build --wait
```

## 4. 访问地址

| 功能 | 地址 |
| --- | --- |
| Nginx/前端统一入口 | <http://127.0.0.1:3000> |
| 经 Nginx 访问 API 文档 | <http://127.0.0.1:3000/docs> |
| 经 Nginx 访问存活检查 | <http://127.0.0.1:3000/health/live> |
| 经 Nginx 访问就绪检查 | <http://127.0.0.1:3000/health/ready> |
| API 本地调试端口 | <http://127.0.0.1:18000/docs> |
| MySQL | `127.0.0.1:13306` |
| Redis | `127.0.0.1:6379` |
| OpenSearch | <http://127.0.0.1:19200> |

所有端口只在本地开发覆盖文件 `compose.override.yaml` 中映射，并仅绑定 `127.0.0.1`；基础 `compose.yaml` 不发布宿主机端口。

## 5. 检查是否启动成功

查看所有容器：

```powershell
docker compose ps -a
```

正常结果：

- `mysql`、`redis`、`opensearch`、`model-gateway`、`api`、`worker`、`frontend`、`nginx` 为 `healthy`。
- `migrate`、`init` 和 `seed` 为 `Exited (0)`，它们不是常驻服务。

首次启动后可使用 `demo-user` 登录并直接测试探店问答，默认开发密码为
`local-life-demo-2026`。该密码仅用于绑定在本机回环地址上的开发环境；如需共享部署，
请在 `.env` 中覆盖 `DEMO_SEED_PASSWORD`。

执行黑盒检查：

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health/live
Invoke-RestMethod http://127.0.0.1:3000/health/ready
Invoke-WebRequest http://127.0.0.1:3000 -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/docs -UseBasicParsing
```

`/health/live` 只证明 API 进程存活，不访问外部依赖。`/health/ready` 会并发检查 MySQL、Redis、OpenSearch 和模型网关；任一依赖不可用时返回 HTTP 503。

正常的就绪响应示例：

```json
{
  "status": "ready",
  "checks": {
    "mysql": "up",
    "redis": "up",
    "opensearch": "up",
    "model_gateway": "up"
  }
}
```

验证 worker 能消费任务：

```powershell
docker compose exec worker celery --app app.worker:celery_app call system.ping
docker compose logs --tail 50 worker
```

## 6. Nginx 流式代理

- `/api/` 原样代理到 FastAPI，适用于 REST 和 SSE。
- WebSocket 自动转发 `Upgrade` 和 `Connection` 请求头。
- API 代理禁用缓存、响应缓冲和请求缓冲，SSE 数据帧会立即转发。
- 流式连接读写超时为 3600 秒。
- `/health/*`、`/docs`、`/redoc` 和 `/openapi.json` 也通过 Nginx 访问 API。

## 7. 查看日志

```powershell
docker compose logs -f
docker compose logs -f nginx api worker frontend
docker compose logs migrate init
```

按 `Ctrl+C` 只会退出日志跟踪，不会停止容器。

## 8. 关闭项目

停止并删除容器和网络，但保留数据库与索引数据：

```powershell
docker compose down
```

只暂停容器：

```powershell
docker compose stop
```

恢复已暂停的容器：

```powershell
docker compose start
```

清空本项目全部本地数据并删除容器：

```powershell
docker compose down --volumes --remove-orphans
```

最后一条命令会永久删除本项目的 MySQL、Redis 和 OpenSearch 数据，只在明确需要重置环境时使用。

### 8.1 查看和清理 Docker 构建缓存

查看镜像、容器、数据卷和构建缓存占用：

```powershell
docker system df
```

清理悬空构建缓存：

```powershell
docker builder prune
```

磁盘空间紧张时，清理所有当前未被构建使用的缓存：

```powershell
docker builder prune -a
```

以上命令不会删除当前镜像、正在运行的容器或 MySQL、Redis、OpenSearch 数据卷。使用 `-a` 后，现有服务仍可直接启动，但下一次镜像构建可能需要重新下载依赖；依赖层重新生成后，后续构建会继续复用缓存。

不要使用 `docker compose down --volumes` 或 `docker volume prune` 代替构建缓存清理，这些命令可能删除本地业务数据。

Docker Desktop 在 Windows 上通常把 Linux 数据存储在动态扩容的 VHDX 虚拟磁盘中。清理缓存后，`docker system df` 会立即下降，但资源管理器中的磁盘剩余空间可能稍后才更新；如果长期没有归还，需要先退出 Docker Desktop，再使用 Docker Desktop 的磁盘回收功能或以管理员权限压缩其 VHDX。压缩前必须确认 Docker Desktop 已完全停止，且不得删除 VHDX 文件本身。

## 9. 本地质量检查

直接在宿主机运行全部质量检查还需要 Python 3.13.14 和 Node.js 22+。使用 `Push-Location` / `Pop-Location` 可确保每组命令结束后回到仓库根目录。

后端：

```powershell
Push-Location backend
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest --cov=app --cov-report=term-missing --cov-fail-under=70
Pop-Location
```

前端：

```powershell
Push-Location frontend
npm ci
npm run lint
npm test
npm run build
Pop-Location
```

在仓库根目录检查 Compose 与代理策略：

```powershell
docker compose config --quiet
python scripts/verify_compose.py
```

CI 配置会执行后端 lint、格式检查、空库迁移和单测，以及前端 lint、组件测试和生产构建；任何一步失败，质量门禁都会失败。

## 10. 常见故障

迁移失败：

```powershell
docker compose logs migrate
```

初始化失败：

```powershell
docker compose logs init
```

API 未就绪：

```powershell
docker compose logs api model-gateway mysql redis opensearch
Invoke-RestMethod http://127.0.0.1:18000/health/ready
```

Nginx 无法访问：

```powershell
docker compose logs nginx frontend api
```

端口冲突时修改 `.env` 中对应的 `*_PORT`，然后重新执行启动命令。
