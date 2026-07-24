# Docker 构建说明

## 多阶段构建架构

Dockerfile 采用多阶段构建，将依赖按用途分层，避免不必要的下载。

```text
FROM public.ecr.aws/docker/library/python:3.13.14-slim AS base
                     |                 核心依赖（fastapi、celery 等）
                     |
                     +-- AS model     <- torch + transformers + embedding
                     |                 仅 model-gateway 使用
                     |
                     +-- AS runtime   <- 应用代码 + core 依赖
                     |                 api / worker / migrate / init / seed
                     |
                     +-- AS test      <- dev 依赖，仅 CI
```

## 各阶段详解

### base 阶段

安装 [project.dependencies] 中的核心依赖：

- fastapi、uvicorn：Web 框架
- sqlalchemy、alembic：数据库
- celery、redis：异步任务队列
- pydantic、PyJWT、argon2-cffi：校验与安全
- opensearch-py：搜索引擎
- langgraph：智能体编排
- python-docx、pypdf、pandas、openpyxl：文档解析

**不包含** torch、transformers 等机器学习依赖。

### model 阶段（FROM base）

在 base 基础上额外安装：

1. 从 PyTorch 官方 CPU Wheels 仓库安装 CPU 版 torch。
2. 从 PyPI 官方仓库安装 transformers、sentence-transformers。
3. 通过 Hugging Face 官方仓库下载 BAAI/bge-small-zh-v1.5 到
   `/models/embedding-cache/bge-small-zh-v1.5`。
4. 设置 `EMBEDDING_MODEL_NAME=BAAI/bge-small-zh-v1.5` 保留模型身份，并通过
   `EMBEDDING_MODEL_PATH=/models/embedding-cache/bge-small-zh-v1.5` 加载构建时下载的 BGE。
5. 设置 `HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`，运行时不再重复联网。

**仅 model-gateway 服务使用**。其他服务构建时完全跳过此阶段。

### runtime 阶段（FROM base）

拷贝应用代码，执行 pip install --no-deps .。使用 --no-deps 避免重复解析依赖。

**所有服务（api、worker、migrate、init、seed）的默认构建目标。**

### test 阶段（FROM base）

额外安装 .[dev] 依赖（pytest、ruff 等），拷贝测试代码。仅 CI 使用。

## 构建行为

| 命令 | 构建阶段 | 下载内容 |
|------|---------|---------|
| docker compose up --build --wait | base -> runtime | core 依赖 |
| model-gateway 单独构建 | base -> model | + torch + transformers + 嵌入模型 |
| CI 测试 | base -> test | + dev 依赖 |

## 镜像源配置

项目统一使用官方上游源，构建前需要确保 Docker Desktop 和 BuildKit 能通过代理访问外网：

| 资源 | 官方源 |
|------|--------|
| Docker 基础镜像 | `public.ecr.aws` |
| Python 包 | `https://pypi.org/simple` |
| npm 包 | `https://registry.npmjs.org` |
| PyTorch CPU Wheels | `https://download.pytorch.org/whl/cpu` |
| 嵌入模型 | Hugging Face `BAAI/bge-small-zh-v1.5` |

Dockerfile 提供相同的默认值，`compose.override.yaml` 显式传入构建参数。本地执行
`docker compose` 时会自动加载该 override；CI 即使只使用 Dockerfile 默认值，也走同一组官方源。

Docker Desktop 应在 Settings -> Resources -> Proxies 中使用系统代理或手动填写代理地址。
仅浏览器能够访问外网并不代表 Docker Desktop 内的 BuildKit 能够使用该代理。

不要把代理地址通过 Dockerfile `ENV` 写入镜像。代理应由 Docker Desktop 或 Docker CLI
构建参数注入，避免将本机代理配置固化到镜像层。

## 依赖分组

backend/pyproject.toml 的依赖分组：

| 组 | 包含 | 安装方式 |
|----|------|---------|
| (默认) | core 依赖 | pip install . |
| model | torch、transformers、sentence-transformers | pip install .[model] |
| training | scikit-learn、accelerate、datasets、peft | pip install .[training] |
| dev | pytest、ruff 等 | pip install .[dev] |
| performance | locust | pip install .[performance] |

## 常见问题

Q: 构建时下载非常慢？
A: 先运行 `docker compose config` 确认合并配置指向上述官方源，再确认 Docker Desktop
的代理设置已生效。代理节点应能稳定访问 AWS Public ECR、PyPI、npm、PyTorch 和 Hugging Face。

Q: 镜像内路径是否表示使用了其他本地 embedding 模型？
A: 不是。构建阶段下载的就是 `BAAI/bge-small-zh-v1.5`。`EMBEDDING_MODEL_NAME`
保留 BGE 模型身份，`EMBEDDING_MODEL_PATH` 仅指向它在镜像内的文件位置。

Q: 为什么运行时不会再次访问 Hugging Face？
A: 模型构建阶段已经从 Hugging Face 下载到镜像内固定目录，model-gateway 通过
`EMBEDDING_MODEL_PATH` 加载同一个 BGE，并启用离线模式。

Q: 改代码后为什么还要等 torch 下载？
A: 如果你修改的是 model-gateway 相关代码，需要重建 model 层。修改 api/worker 代码不会触发 torch 下载。
