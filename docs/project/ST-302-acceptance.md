# ST-302 OpenAI/WebSocket 与安全工具调用整体验收说明

## 1. 验收范围与结论

本文依据《大众点评AI智能助手-02-需求分析》《大众点评AI智能助手-03-API接口规范》《大众点评AI智能助手-05-具体设计》和《大众点评AI智能助手-06-人员分工任务分配》，核对 ST-302 及 TK-302-01～TK-302-04 的实现、生产接线和自动化证据。

结论：**ST-302 已整体达标**。OpenAI 非流式/SSE、WebSocket 生命周期和受控工具执行均已接入同一生产 `ChatAgentRuntime`；当前只注册最小权限的只读 `knowledge.search`，HTTP 与 WebSocket 入口均向执行器传递服务端认证主体和可信检索范围，成功、拒绝、失败与超时调用统一写入追加式审计。

## 2. 子任务交付核对

| Task | 已有实现与证据 | 核对结果 |
| --- | --- | --- |
| TK-302-01 | `app/api/openai.py` 提供非流式 `chat.completion`、兼容错误映射；OpenAI Python SDK 集成测试可解析响应 | 通过 |
| TK-302-02 | SSE chunk/`[DONE]`、WebSocket ack/route/delta/sources/completed/error、心跳、取消和断连清理 | 通过 |
| TK-302-03 | `ToolRegistry`、严格 Pydantic 参数校验、权限与资源范围校验、最长 30 秒超时、失败关闭审计；生产装配 `knowledge.search` 和 SQLAlchemy 审计仓储 | 通过 |
| TK-302-04 | SDK、事件顺序、流式异常、断连、运行时工具成功/拒绝链路及首包阈值集成测试 | 通过 |

## 3. Story 验收准则核对

| 验收准则 | 证据 | 结果 |
| --- | --- | --- |
| ① 非流式响应可被常用 OpenAI SDK 解析 | `test_chat_transports_integration.py::test_openai_sdk_parses_non_streaming_and_streaming_responses` | 通过 |
| ② SSE 顺序兼容、以 `[DONE]` 结束、异常返回兼容错误对象 | `test_openai_compat.py` 与 `test_chat_transports_integration.py` 覆盖首 chunk、内容、finish chunk、错误对象和 `[DONE]` | 通过 |
| ③ WebSocket 输出规定事件并支持取消、断连清理 | `test_websocket_chat.py` 和集成测试覆盖事件顺序、取消、异常终止与断连取消下游任务 | 通过 |
| ④ 心跳不超过 30 秒，演示环境首包不高于 2 秒 | WebSocket 对配置值强制上限 30 秒；SSE 首 chunk 与 WebSocket ack 在下游运行前发送，端到端工具测试断言首个 ack 小于 2 秒 | 通过 |
| ⑤ 非法工具调用均拒绝并记录 | 单元测试及 `test_agent_tool_runtime.py` 覆盖生产同构链路中的未注册、参数非法、无权限、资源越权、超时、执行失败和审计失败关闭 | 通过 |
| ⑥ 工具环境禁止任意代码及数据库/Docker 高权限 | 只允许代码内静态注册异步处理器，禁止动态导入、求值和命令参数；处理器只持有检索端口与可信范围。Compose 门禁验证非 root、只读文件系统、`no-new-privileges`、无 Docker socket 和内部后端网络 | 通过 |

## 4. 生产闭环

### 4.1 运行时接线

生产 `app/main.py` 显式构造 `ToolRegistry`、`ToolExecutor` 与 `SQLAlchemyToolAuditRepository`，注册 `knowledge.search` 后注入 `ChatAgentRuntime`。工具意图经过以下链路：

```text
OpenAI / WebSocket
  → AuthorizationPrincipal + RetrievalScope
  → RegisteredToolPlanner
  → ToolRegistry
  → args_schema 严格校验
  → RBAC 权限校验
  → 超时控制
  → knowledge.search
  → audit_logs
  → 引用持久化与流式输出
```

自然语言工具意图默认映射到 `knowledge.search`；开发与集成调用也可使用严格 JSON 信封：

```text
调用工具：{"name":"knowledge.search","arguments":{"query":"安静川菜","top_k":5}}
```

名称不在注册表、信封或参数不合法、缺少权限、资源越权及超时均失败关闭；审计只保存字段名和参数哈希，不保存参数值。

### 4.2 最小权限与运行隔离

- `knowledge.search` 处理器只接收已校验参数、调用上下文和 `RetrieverAdapter`，无法由请求注入模块、代码、文件路径或命令。
- 可信租户与知识库范围由服务端认证主体生成，不接受模型或客户端覆盖。
- API 容器使用非 root 用户、只读根文件系统、临时目录和 `no-new-privileges`，未挂载 Docker socket；API 环境不包含 MySQL root 密码。
- 若后续增加 Pandas、脚本或其他代码执行类工具，必须使用设计文档规定的独立沙箱，不能复用当前进程内处理器模式。

## 5. 自动化门禁

1. OpenAI SDK 同时解析非流式和 SSE 响应，兼容错误对象并校验 `[DONE]`。
2. WebSocket 校验事件顺序、心跳、取消、异常终止、断连清理和重复请求。
3. 运行时工具测试从 `ChatAgentRuntime.run()` 进入，覆盖成功、未注册、参数非法、无权限和格式非法，并核对审计不保存参数值。
4. OpenAI 与 WebSocket 端到端测试执行实际注册工具链；WebSocket 首个 ack 断言小于 2 秒。
5. `scripts/verify_compose.py` 对工具所在应用容器执行最小权限和 Docker socket 静态门禁。

## 6. 本次验证结果

执行：

```powershell
Push-Location backend
..\.venv\Scripts\ruff.exe check .
..\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

结果：

- Ruff：PASS。
- 后端测试：923 passed，39 skipped；跳过项为需要外部 MySQL 等依赖的条件测试。
- ST-302 专项测试：25 passed。
- Compose 安全门禁：PASS。

结论：ST-302 在当前故事边界内通过实现、生产接线、传输集成、工具安全和容器权限验收。
