# 本地开发与 CI

## 环境要求

- Docker Desktop 或 Docker Engine，支持 Compose v2
- 建议为 Docker 分配至少 4 GB 内存；OpenSearch JVM 默认使用 512 MB 堆
- 单独运行源码检查时需要 Python 3.11+ 与 Node.js 22+

`.env.example` 只包含可公开的开发默认值。需要改端口或本地凭据时先复制为 `.env`；不要提交 `.env`，生产环境必须通过密钥管理系统注入新凭据。

## 启动与停止

在仓库根目录执行：

```bash
docker compose up --build --wait
```

该命令会依次等待 MySQL、Redis、OpenSearch 健康，运行一次 Alembic 迁移，再启动 API 和前端。查看状态与日志：

```bash
docker compose ps
docker compose logs -f api frontend
```

停止服务但保留数据：

```bash
docker compose down
```

仅在明确要清空本地 MySQL、Redis 和 OpenSearch 数据时执行：

```bash
docker compose down --volumes
```

## 端口隔离

基础 `compose.yaml` 只发布面向开发者的 API 和前端端口，不发布 MySQL、Redis、OpenSearch。Docker Compose 在本地默认自动叠加 `compose.override.yaml`，其中依赖端口全部只绑定回环地址：

| 服务 | 本地地址 |
| --- | --- |
| MySQL | `127.0.0.1:13306` |
| Redis | `127.0.0.1:6379` |
| OpenSearch | `127.0.0.1:19200` |
| OpenSearch Performance Analyzer | `127.0.0.1:19600` |

检查不带开发覆盖的基础配置：

```bash
docker compose -f compose.yaml config
```

测试或部署环境必须显式指定自己的覆盖文件，不能复用开发端口映射和开发凭据。

## 健康检查

- `/health/live` 只证明 API 进程存活，不访问外部依赖。
- `/health/ready` 并发检查 MySQL、Redis 与 OpenSearch；任一依赖失败时返回 HTTP 503，并且不回传连接错误或凭据。
- Compose 以 `service_healthy` 编排依赖，以 `service_completed_successfully` 确认迁移成功。

模型网关不属于 LLA-108 要求的基础服务；后续接入模型运行时后，应把它加入 `/health/ready` 的检查集合。

## 本地质量检查

后端：

```bash
cd backend
python -m venv .venv
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
python -m pytest --cov=app --cov-fail-under=70
```

前端：

```bash
cd frontend
npm ci
npm run lint
npm test
npm run build
```

## CI 与合并门禁

`.github/workflows/ci.yml` 在 PR 和 `main` 分支推送时运行：

- 后端 Ruff、格式、空库 Alembic 全量迁移、Pytest 与 70% 覆盖率门槛
- 前端 ESLint、Vitest、TypeScript/Vite 构建
- Compose 语法、必需健康检查、依赖端口隔离策略
- API/前端镜像构建，并使用 GitHub Actions layer cache
- pip 与 npm 依赖缓存

## 常见问题

- OpenSearch 长时间不健康：提高 Docker Desktop 内存；Linux 主机还需确保 `vm.max_map_count` 至少为 `262144`。
- 端口冲突：在 `.env` 修改对应的 `*_PORT`，然后重新启动。
- 迁移失败：运行 `docker compose logs migrate`；修复后再次执行启动命令，迁移任务会重新创建。
- 查看单个依赖健康信息：运行 `docker inspect --format '{{json .State.Health}}' <container>`。
