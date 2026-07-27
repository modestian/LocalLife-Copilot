# TK-703-03 Locust 性能门禁结果

- 生成时间：`2026-07-26T04:49:56.678659+00:00`
- 原始统计：`D:\LocalLife-Copilot\docs\测试用例文档\execution_results\2026-07-26-current\performance\locust_stats.csv`
- 每项最小样本数：`20`
- 总体结论：**PASS**

| 场景 | 样本 | 失败 | P95 | 门槛 | 结果 | 说明 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| API GET /api/v1/users/me | 1342 | 0 | 58 ms | < 500 ms | PASS | 通过 |
| SEARCH POST /api/v1/search | 1293 | 0 | 180 ms | < 300 ms | PASS | 通过 |
| TTFB POST /v1/chat/completions | 1263 | 0 | 99 ms | ≤ 2000 ms | PASS | 通过 |

P95 取自 Locust 聚合统计；流式场景覆盖从请求发出到首个非空 SSE `data:` 帧到达的墙钟耗时。任一场景缺失、样本不足、出现失败或超出延迟门槛，门禁均失败。
