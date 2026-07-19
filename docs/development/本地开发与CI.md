# 本地开发与 CI 基线

## 一键启动

```powershell
Copy-Item .env.example .env
docker compose up --build --wait
```

Compose 启动链为：

```text
MySQL healthy -> migrate(0) -> init(0) -> api/worker healthy
Redis/OpenSearch/model-gateway healthy -------^       |
api healthy -> frontend healthy -> nginx healthy <---+
```

`migrate` 只执行 `alembic upgrade head`。`init` 单独幂等创建 OpenSearch 索引。任何一次性任务失败，API 和 worker 都不会启动。

## 服务与端口

基础 `compose.yaml` 不映射任何宿主机端口。本地运行时 Compose 自动合并 `compose.override.yaml`，只在 `127.0.0.1` 映射以下端口：

| 服务 | 本地端口 |
| --- | --- |
| Nginx | `3000` |
| API 调试 | `18000` |
| MySQL | `13306` |
| Redis | `6379` |
| OpenSearch | `19200` |
| OpenSearch Performance Analyzer | `19600` |

## 健康检查

- `/health/live` 只检查 API 进程，不访问外部依赖。
- `/health/ready` 并发检查 MySQL、Redis、OpenSearch 和模型网关。
- 任一就绪依赖失败时返回 HTTP 503，并且响应不泄露连接异常或凭据。
- worker 使用 Celery control ping 检查自身消费进程。

## Nginx

Nginx 是浏览器统一入口：

- `/` 代理到前端。
- `/api/` 原样代理到 FastAPI。
- `/health/*`、`/docs`、`/redoc`、`/openapi.json` 代理到 FastAPI。
- WebSocket 转发 Upgrade/Connection 请求头。
- SSE/API 禁止代理缓存、响应缓冲和请求缓冲，读写超时为 3600 秒。

## 本地检查

本机后端开发与检查统一使用 Python 3.13.14；仓库根目录 `.python-version`、Docker 镜像和 CI 锁定该版本，后端包允许兼容的 Python 3.13 补丁版本。

首次检出仓库或重新创建 `.git` 目录后，在仓库根目录安装质量检查 Hook：

```powershell
py -3.13 scripts/install_git_hooks.py
```

- `pre-commit` 在创建提交前执行后端 Ruff lint 和格式检查，失败时阻止提交。
- `pre-push` 在推送前再次执行 Ruff、完整后端测试和 70% 覆盖率门禁，失败时阻止推送。
- Hook 不替代 CI；空 MySQL 库迁移仍由 CI 执行。不得使用 `--no-verify` 绕过质量门禁。

后端：

```powershell
cd backend
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest --cov=app --cov-report=term-missing --cov-fail-under=70
```

前端：

```powershell
cd frontend
npm ci
npm run lint
npm test
npm run build
```

Compose 策略：

```powershell
docker compose config --quiet
python scripts/verify_compose.py
```

## CI 质量门禁

CI 包含：

- 后端 Ruff lint、格式检查、空 MySQL 库 Alembic 迁移、Pytest 与 70% 覆盖率门槛。
- 前端 npm audit、ESLint、Vitest 组件测试和 Vite 生产构建。
- Compose 基础/开发配置解析、健康检查、启动依赖和端口隔离策略。
- 后端、前端和 Nginx 镜像构建缓存。
- 汇总质量门禁；任何前置任务失败，最终门禁失败。

## 停止

```powershell
docker compose down
```

需要连本地数据一起重置时才执行：

```powershell
docker compose down --volumes --remove-orphans
```
