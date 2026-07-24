# Docker 构建说明

## 多阶段构建架构

Dockerfile 采用多阶段构建，将依赖按用途分层，避免不必要的下载。

`
FROM python:3.13.14-slim AS base      <- 核心依赖（fastapi、celery 等）
                     |
                     +-- AS model     <- torch + transformers + embedding
                     |                 仅 model-gateway 使用
                     |
                     +-- AS runtime   <- 应用代码 + core 依赖
                     |                 api / worker / migrate / init / seed
                     |
                     +-- AS test      <- dev 依赖，仅 CI
`

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

1. pip install .[model]：torch（CPU-only）、transformers、sentence-transformers
2. 预下载 BAAI/bge-small-zh-v1.5 嵌入模型到 /models/embedding-cache

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

### 国内加速（本地开发）

compose.override.yaml 自动加载，为每个 backend 服务的 build.args 设置：

PIP_INDEX_URL: https://pypi.tuna.tsinghua.edu.cn/simple
TORCH_INDEX_URL: https://mirrors.aliyun.com/pytorch-whl/cpu

### 默认源（CI）

compose.yaml 不设置镜像参数，Dockerfile 默认使用：

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

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
A: 检查是否使用了国内镜像。本地开发应确保 compose.override.yaml 存在并包含镜像配置。

Q: 改代码后为什么还要等 torch 下载？
A: 如果你修改的是 model-gateway 相关代码，需要重建 model 层。修改 api/worker 代码不会触发 torch 下载。