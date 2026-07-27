# Retrieval evaluation (TK-202-06)

`search_benchmark_v1.json` freezes a synthetic, privacy-safe demo corpus, 20 queries and relevance
judgments. The evaluator reuses the production `HybridSearchService` and mandatory trusted scope;
its isolated `local-life-search-eval-v1` index never changes the application read/write aliases.

With OpenSearch running, execute from the repository root:

```powershell
Push-Location backend
python evaluation/evaluate_search.py --prepare-index
Pop-Location
```

The command is idempotent and writes JSON and Markdown under `backend/evaluation/reports/`.
Recall@5 is macro-averaged set recall, MRR@10 uses the first relevant merchant, and P95 uses the
nearest-rank definition over production service wall-clock latency. The current local embedding
gateway implements deterministic vectors; the evaluator uses the exact same algorithm so host
execution also includes query-embedding time.
