# TK-703-03 Locust 性能门禁

本门禁在演示规模数据下测量三条生产接口链路：已鉴权 API、权限安全的混合检索，以及 OpenAI 兼容 SSE 的首包。任一场景缺失、样本不足、出现失败请求或超出 P95 门槛时，判定脚本都会以非零状态退出。

| Locust 场景 | 测量范围 | P95 门槛 |
| --- | --- | ---: |
| `API GET /api/v1/users/me` | HTTP、JWT 校验、RBAC 数据查询和响应序列化 | `< 500 ms` |
| `SEARCH POST /api/v1/search` | HTTP、鉴权、Embedding、BM25 + k-NN、融合/重排和响应序列化 | `< 300 ms` |
| `TTFB POST /v1/chat/completions` | 从发送请求到收到首个非空 SSE `data:` 帧 | `≤ 2,000 ms` |

## 准备环境

安装后端性能测试依赖，并启动已迁移、已初始化且健康的完整服务：

```powershell
cd backend
py -3.13 -m pip install -e ".[dev,performance]"
cd ..

docker compose up -d --build
docker compose ps
```

压测账号必须具有固定知识库 `70200000-0000-4000-8000-000000000010` 的读取权限。可复用 ST-702 的确定性演示账号；密码只能临时放在当前进程环境中，不得写入仓库或命令参数：

```powershell
$env:DEMO_SEED_PASSWORD = Read-Host "Demo seed password"
docker compose exec -e DEMO_SEED_PASSWORD api python -m app.cli.seed_demo_data

$env:PERF_USERNAME = "demo-admin"
$env:PERF_PASSWORD = $env:DEMO_SEED_PASSWORD
```

## 执行与判定

默认以 12 个并发用户、每秒 3 个用户的速率预热并运行 2 分钟，每项至少要求 20 个样本：

```powershell
.\scripts\run_tk703_performance.ps1
```

需要调整负载或目标服务时显式传参：

```powershell
.\scripts\run_tk703_performance.ps1 `
  -TargetHost "http://127.0.0.1:18000" `
  -Users 20 `
  -SpawnRate 5 `
  -RunTime "5m" `
  -MinimumRequests 100
```

原始 CSV、HTML 报告、JSON 判定和 Markdown 摘要写入 `artifacts/tk-703-03/`。该目录不进入 Git；正式验收时应将 Markdown 摘要中的实测值和执行环境记录到 `docs/reports/`。Locust 的登录初始化指标不参与门禁，三项业务统计均必须存在。

执行器固定从仓库根目录启动 Locust，并临时把 `backend` 加入 `PYTHONPATH`。这是为了避开 Locust 2.46.1 在部分中文 Windows 环境中按 GBK 自动读取 UTF-8 `backend/pyproject.toml` 的问题；脚本退出时会恢复原有 `PYTHONPATH`。

流式请求使用 `stream=True`，并将 Locust 的响应时间改写为首个非空 SSE 数据帧到达时的墙钟耗时，避免只统计响应头到达时间。收到首帧后客户端主动关闭流，服务端据此取消未完成任务，因此本场景不测完整生成耗时。

完成后清除当前会话中的敏感变量：

```powershell
Remove-Item Env:PERF_PASSWORD -ErrorAction SilentlyContinue
Remove-Item Env:DEMO_SEED_PASSWORD -ErrorAction SilentlyContinue
```
