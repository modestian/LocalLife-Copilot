# LocalLife Copilot 项目启动文档

LocalLife Copilot 是一个本地生活 AI 助手基础工程，包含以下服务：

- Vue 3 前端
- FastAPI API
- MySQL 8.4
- Redis 7.4
- OpenSearch 3.7
- Alembic 数据库迁移任务

项目使用 Docker Compose 编排，正常情况下不需要在宿主机单独安装 Python、Node.js、MySQL、Redis 或 OpenSearch。

## 1. 启动前准备

请先安装并启动 Docker Desktop，确认终端可以执行：

```powershell
docker version
docker compose version
```

建议为 Docker Desktop 分配至少 4 GB 内存，并保证磁盘至少有 8 GB 可用空间。

进入项目根目录：

```powershell
cd D:\Dazhong\LocalLife-Copilot
```

如果 `docker` 命令不在 PATH 中，可以在本机 PowerShell 使用完整路径：

```powershell
& 'C:\Users\HP\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' compose version
```

## 2. 环境配置

项目自带安全的本地开发默认值，不创建 `.env` 也可以直接启动。

如需修改端口或开发数据库密码，可以复制示例配置：

```powershell
Copy-Item .env.example .env
```

默认端口如下：

| 服务 | 本地地址 |
| --- | --- |
| 前端 | `http://127.0.0.1:3000` |
| API | `http://127.0.0.1:18000` |
| MySQL | `127.0.0.1:13306` |
| Redis | `127.0.0.1:6379` |
| OpenSearch | `http://127.0.0.1:19200` |
| OpenSearch Performance Analyzer | `127.0.0.1:19600` |

MySQL、Redis 和 OpenSearch 的端口只在本地开发覆盖文件中映射，并且仅绑定 `127.0.0.1`。

## 3. 首次启动

在项目根目录执行：

```powershell
docker compose up --build --wait
```

该命令会完成以下操作：

1. 构建 frontend、api 和 migrate 镜像。
2. 启动 MySQL、Redis 和 OpenSearch。
3. 等待三个依赖通过健康检查。
4. 执行 Alembic 数据库迁移。
5. 启动 API 并等待 `/health/ready` 通过。
6. 启动前端并等待前端健康检查通过。

首次构建需要下载镜像和依赖，耗时会比后续启动更长。

## 4. 日常启动

镜像已经构建且代码没有变化时，可以执行：

```powershell
docker compose up -d --wait
```

修改了代码、依赖或 Dockerfile 后，重新构建并启动：

```powershell
docker compose up --build --wait
```

如果终端找不到 `docker`，使用本机 Docker Desktop 完整路径：

```powershell
& 'C:\Users\HP\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe' compose up --build --wait
```

## 5. 检查启动状态

查看所有服务：

```powershell
docker compose ps -a
```

正常状态应满足：

- `mysql`、`redis`、`opensearch`、`api`、`frontend` 显示 `healthy`。
- `migrate` 显示 `Exited (0)`，表示数据库迁移成功；它不是常驻服务。

查看全部日志：

```powershell
docker compose logs -f
```

只查看 API 和前端日志：

```powershell
docker compose logs -f api frontend
```

只查看迁移日志：

```powershell
docker compose logs migrate
```

按 `Ctrl+C` 退出日志跟踪不会停止容器。

## 6. 访问项目

启动成功后访问：

- 前端页面：<http://localhost:3000>
- Swagger API 文档：<http://localhost:18000/docs>
- API 存活检查：<http://localhost:18000/health/live>
- API 就绪检查：<http://localhost:18000/health/ready>
- OpenSearch 集群状态：<http://localhost:19200/_cluster/health>

PowerShell 验证命令：

```powershell
Invoke-RestMethod http://127.0.0.1:18000/health/live
Invoke-RestMethod http://127.0.0.1:18000/health/ready
Invoke-RestMethod http://127.0.0.1:19200/_cluster/health
```

`/health/ready` 的正常返回示例：

```json
{
  "status": "ready",
  "checks": {
    "mysql": "up",
    "redis": "up",
    "opensearch": "up"
  }
}
```

## 7. 停止项目

### 7.1 停止并删除容器，保留数据

推荐使用：

```powershell
docker compose down
```

该命令会删除项目容器和网络，但保留 MySQL、Redis、OpenSearch 数据卷。下次启动时数据仍然存在。

### 7.2 只停止容器

```powershell
docker compose stop
```

重新启动已停止的容器：

```powershell
docker compose start
```

启动后检查状态：

```powershell
docker compose ps -a
```

### 7.3 停止并清空所有本地数据

以下命令会永久删除本项目的 MySQL、Redis 和 OpenSearch 数据，只能在明确需要重置开发环境时使用：

```powershell
docker compose down --volumes --remove-orphans
```

清空后再次启动：

```powershell
docker compose up --build --wait
```

## 8. 常用维护命令

重新构建单个服务：

```powershell
docker compose build api
docker compose build frontend
```

重新创建单个服务：

```powershell
docker compose up -d --build api
docker compose up -d --build frontend
```

验证 Compose 配置：

```powershell
docker compose config --quiet
```

查看容器资源占用：

```powershell
docker stats
```

查看磁盘占用：

```powershell
docker system df
```

## 9. 常见问题

### 9.1 端口被占用

复制 `.env.example` 为 `.env`，修改对应端口后重新启动：

```powershell
Copy-Item .env.example .env
docker compose up -d --wait
```

如果修改了 `FRONTEND_PORT`，同时更新 `.env` 中的 `CORS_ORIGINS`。如果修改了 `API_PORT`，需要使用 `--build` 重新构建前端。

### 9.2 迁移失败

```powershell
docker compose logs migrate
docker compose up -d
```

### 9.3 API 未就绪

```powershell
docker compose logs api
Invoke-RestMethod http://127.0.0.1:18000/health/ready
```

### 9.4 OpenSearch 长时间不健康

提高 Docker Desktop 可用内存，然后重新启动：

```powershell
docker compose restart opensearch
docker compose ps -a
```

### 9.5 完整重启项目

保留数据并完整重启：

```powershell
docker compose down
docker compose up --build --wait
```

## 10. 最简命令汇总

首次启动或代码更新后启动：

```powershell
docker compose up --build --wait
```

日常启动：

```powershell
docker compose up -d --wait
```

停止项目并保留数据：

```powershell
docker compose down
```

停止项目并删除全部本地数据：

```powershell
docker compose down --volumes --remove-orphans
```
