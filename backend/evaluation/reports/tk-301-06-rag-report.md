# TK-301-06 RAG 固定集评测报告

- 生成时间：`2026-07-21T07:23:06.528324+00:00`
- 数据集：`tk-301-06-v1`
- SHA-256：`fe9a35ac12e6b4264d234e1f98d173c154e5e9920ae8366ab7d9bbdac293536d`
- 用例数：20（每类 5 例）
- 口径：直接执行生产约束抽取、路由、Grounded RAG 与 Citation Verifier；不调用外部模型或搜索服务。

| 指标 | 实测 | 门槛 | 结果 |
| --- | ---: | ---: | --- |
| 多轮上下文准确率 | 1.0000 | ≥ 0.90 | PASS |
| 引用正确率 | 1.0000 | ≥ 0.95 | PASS |
| 幻觉拦截率 | 1.0000 | ≥ 0.90 | PASS |
| 无结果兜底准确率 | 1.0000 | ≥ 0.90 | PASS |

总体结论：**PASS**。

## 逐例结果

| ID | 类别 | 结果 | 兜底原因 / 引用 |
| --- | --- | --- | --- |
| mt-01 | multi_turn | PASS | ask_question → hybrid_retrieve |
| mt-02 | multi_turn | PASS | ask_question → hybrid_retrieve |
| mt-03 | multi_turn | PASS | ask_question → hybrid_retrieve → hybrid_retrieve |
| mt-04 | multi_turn | PASS | ask_question → ask_question → hybrid_retrieve |
| mt-05 | multi_turn | PASS | ask_question → hybrid_retrieve |
| ct-01 | citation | PASS | E1 |
| ct-02 | citation | PASS | E1, E2 |
| ct-03 | citation | PASS | E1 |
| ct-04 | citation | PASS | E1 |
| ct-05 | citation | PASS | E1, E2 |
| hl-01 | hallucination | PASS | unsupported_citations |
| hl-02 | hallucination | PASS | invalid_model_output |
| hl-03 | hallucination | PASS | invalid_model_output |
| hl-04 | hallucination | PASS | unsupported_citations |
| hl-05 | hallucination | PASS | unsupported_citations |
| nr-01 | no_result | PASS | no_evidence |
| nr-02 | no_result | PASS | no_evidence |
| nr-03 | no_result | PASS | insufficient_evidence |
| nr-04 | no_result | PASS | no_evidence |
| nr-05 | no_result | PASS | insufficient_evidence |
