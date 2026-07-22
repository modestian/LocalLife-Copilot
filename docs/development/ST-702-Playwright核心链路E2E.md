# ST-702 Playwright 核心链路 E2E（TK-702-02）

`frontend/e2e/st-702-core-flows.spec.ts` 使用浏览器真实页面、登录状态和 API 路由契约，覆盖以下确定性验收场景：

1. 管理员登录、上传文档并轮询至索引完成；
2. 普通用户查看探店引用、校验来源跳转地址、提交反馈及无结果兜底；
3. 商家查看授权商家的趋势、拦截未授权商家；
4. 索引任务失败后显示可重试状态。

测试对后端请求使用 Playwright 路由拦截，因而不依赖外部模型、OpenSearch 或异步 Worker 的实时状态；请求和响应结构仍与 API 契约保持一致。真实环境的上传、索引和三次连续执行由后续验收编排基于 TK-702-01 初始化数据执行。

```powershell
cd frontend
npm ci
npx playwright install chromium
npm run test:e2e -- st-702-core-flows.spec.ts
```

失败时 Playwright 会保留 trace；运行结果可在终端 reporter 中查看。执行前不需要把演示密码写入前端代码或环境文件。
