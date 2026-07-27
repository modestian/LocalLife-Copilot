# TK-202-06 检索评测报告

- 生成时间：`2026-07-19T04:59:14.498408+00:00`
- 数据集：`tk-202-06-v1`
- SHA-256：`1bcd4548e44982e737eee51c559069e2a9d4c6c6e1f05143e5ce15b52f39a2c6`
- 隔离索引：`local-life-search-eval-v1`（演示数据规模）
- 查询数 / 延迟样本数：20 / 100
- P95 口径：生产 `HybridSearchService.search` 墙钟耗时，包含查询 Embedding、BM25+k-NN 双路召回与融合；不包含 HTTP、鉴权和 LLM。

| 指标 | 实测 | 验收阈值 | 结果 |
| --- | ---: | ---: | --- |
| Recall@5 | 0.9500 | ≥ 0.80 | PASS |
| MRR@10 | 0.9500 | ≥ 0.65 | PASS |
| P95 | 18.491 ms | < 300 ms | PASS |

总体结论：**PASS**。

## 逐题结果

| ID | Recall@5 | RR@10 | Top 3 merchant_id |
| --- | ---: | ---: | --- |
| q01 | 1.00 | 1.00 | eval-m01, eval-m03, eval-m08 |
| q02 | 1.00 | 1.00 | eval-m01, eval-m04, eval-m05 |
| q03 | 1.00 | 1.00 | eval-m02, eval-m07, eval-m12 |
| q04 | 1.00 | 1.00 | eval-m02, eval-m07, eval-m09 |
| q05 | 1.00 | 1.00 | eval-m03, eval-m11, eval-m01 |
| q06 | 1.00 | 1.00 | eval-m04, eval-m06, eval-m09 |
| q07 | 1.00 | 1.00 | eval-m05, eval-m03, eval-m01 |
| q08 | 1.00 | 1.00 | eval-m06, eval-m02, eval-m12 |
| q09 | 1.00 | 1.00 | eval-m07, eval-m09, eval-m01 |
| q10 | 1.00 | 1.00 | eval-m08, eval-m06, eval-m12 |
| q11 | 1.00 | 1.00 | eval-m09, eval-m05, eval-m03 |
| q12 | 1.00 | 0.50 | eval-m01, eval-m10, eval-m06 |
| q13 | 1.00 | 0.50 | eval-m07, eval-m11, eval-m03 |
| q14 | 1.00 | 1.00 | eval-m12, eval-m04, eval-m06 |
| q15 | 0.50 | 1.00 | eval-m12, eval-m11, eval-m09 |
| q16 | 0.50 | 1.00 | eval-m10, eval-m11, eval-m06 |
| q17 | 1.00 | 1.00 | eval-m05, eval-m06, eval-m09 |
| q18 | 1.00 | 1.00 | eval-m09, eval-m01, eval-m08 |
| q19 | 1.00 | 1.00 | eval-m12, eval-m02, eval-m11 |
| q20 | 1.00 | 1.00 | eval-m06, eval-m12, eval-m09 |
