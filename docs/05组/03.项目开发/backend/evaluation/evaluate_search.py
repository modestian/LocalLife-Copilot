"""TK-202-06 isolated retrieval benchmark and report generator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

from app.etl.embeddings import BatchedEmbedder
from app.infrastructure.search.indexes import chunk_index_body
from app.infrastructure.search.pipeline import HybridSearchService
from app.infrastructure.search.ranking import RankingConfig
from app.infrastructure.search.retrieval import OpenSearchDualRetriever, TrustedSearchScope
from app.infrastructure.search.service import HybridRecallService

DEFAULT_DATASET = Path(__file__).with_name("search_benchmark_v1.json")
DEFAULT_REPORT_JSON = Path(__file__).with_name("reports") / "tk-202-06-search-report.json"
DEFAULT_REPORT_MD = Path(__file__).with_name("reports") / "tk-202-06-search-report.md"


class DeterministicEmbeddingProvider:
    """Exact local equivalent of the current model-gateway embedding contract."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = text.encode("utf-8")
        return [
            int.from_bytes(hashlib.sha256(seed + offset.to_bytes(4, "big")).digest()[:4], "big")
            / (2**31)
            - 1.0
            for offset in range(self.dimension)
        ]


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("latency sample must not be empty")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def metrics_for_rankings(
    cases: Sequence[Mapping[str, Any]], rankings: Mapping[str, Sequence[str]]
) -> tuple[float, float, list[dict[str, Any]]]:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    details: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case["id"])
        relevant = set(case["relevant_merchant_ids"])
        returned = list(rankings[case_id])
        recall = len(relevant.intersection(returned[:5])) / len(relevant)
        first_rank = next(
            (rank for rank, item in enumerate(returned[:10], 1) if item in relevant), None
        )
        reciprocal_rank = 1.0 / first_rank if first_rank is not None else 0.0
        recalls.append(recall)
        reciprocal_ranks.append(reciprocal_rank)
        details.append(
            {
                "id": case_id,
                "query": case["query"],
                "relevant_merchant_ids": sorted(relevant),
                "returned_merchant_ids": returned[:10],
                "recall_at_5": recall,
                "reciprocal_rank_at_10": reciprocal_rank,
            }
        )
    return statistics.fmean(recalls), statistics.fmean(reciprocal_ranks), details


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("schema_version") != 1:
        raise ValueError("unsupported search benchmark schema_version")
    cases, documents = dataset.get("cases"), dataset.get("documents")
    if not isinstance(cases, list) or not cases or not isinstance(documents, list) or not documents:
        raise ValueError("benchmark must contain non-empty documents and cases")
    case_ids = [case.get("id") for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("benchmark case ids must be unique")
    known_merchants = {document.get("merchant_id") for document in documents}
    for case in cases:
        relevant = case.get("relevant_merchant_ids")
        if not isinstance(relevant, list) or not relevant or not set(relevant) <= known_merchants:
            raise ValueError(f"invalid relevance judgment for case {case.get('id')}")
    return dataset, hashlib.sha256(raw).hexdigest()


def prepare_index(
    client: OpenSearch,
    *,
    index: str,
    dataset: Mapping[str, Any],
    dataset_sha256: str,
    embedder: BatchedEmbedder,
    dimension: int,
) -> None:
    if not client.indices.exists(index=index):
        body = chunk_index_body(dimension)
        body["settings"]["index.evaluation_dataset_sha256"] = dataset_sha256
        client.indices.create(index=index, body=body)
    stored_hash = client.indices.get_settings(index=index)[index]["settings"]["index"].get(
        "evaluation_dataset_sha256"
    )
    if stored_hash != dataset_sha256:
        raise RuntimeError(f"isolated index {index!r} belongs to a different dataset")

    documents = dataset["documents"]
    vectors = embedder.embed([document["content"] for document in documents])
    scope = dataset["scope"]
    actions = []
    for document, vector in zip(documents, vectors, strict=True):
        merchant_id = document["merchant_id"]
        actions.append(
            {
                "_op_type": "index",
                "_index": index,
                "_id": f"{dataset['dataset_version']}:{merchant_id}",
                "_source": {
                    "chunk_id": f"chunk-{merchant_id}",
                    "document_id": f"document-{merchant_id}",
                    "document_version_id": f"version-{merchant_id}",
                    "tenant_id": scope["tenant_id"],
                    "knowledge_base_id": scope["knowledge_base_id"],
                    "merchant_id": merchant_id,
                    "content": document["content"],
                    "content_vector": vector,
                    "source_key": "search_benchmark_v1.json",
                    "source_type": "merchant",
                    "source_location": f"TK-202-06/{merchant_id}",
                    "category_ids": document["category_ids"],
                    "price_cent": document["price_cent"],
                    "business_status": "OPEN",
                    "resource_scope": [f"KNOWLEDGE_BASE:{scope['knowledge_base_id']}"],
                    "chunk_no": 0,
                    "content_hash": hashlib.sha256(document["content"].encode()).hexdigest(),
                    "token_count": len(document["content"]),
                    "metadata": {"benchmark": dataset["dataset_version"]},
                    "updated_at": "2026-07-19T00:00:00Z",
                },
            }
        )
    bulk(client, actions, refresh="wait_for")
    if client.count(index=index)["count"] != len(documents):
        raise RuntimeError("isolated evaluation index contains unexpected documents")


def evaluate(
    client: OpenSearch,
    *,
    index: str,
    dataset: Mapping[str, Any],
    dataset_sha256: str,
    embedder: BatchedEmbedder,
    repeats: int,
    warmups: int,
) -> dict[str, Any]:
    scope_data = dataset["scope"]
    kb_id = scope_data["knowledge_base_id"]
    scope = TrustedSearchScope(
        tenant_id=scope_data["tenant_id"],
        knowledge_base_ids=frozenset({kb_id}),
        resource_scopes=frozenset({f"KNOWLEDGE_BASE:{kb_id}"}),
    )
    service = HybridSearchService(
        HybridRecallService(embedder, OpenSearchDualRetriever(client, index=index))
    )
    config = RankingConfig(
        method="weighted",
        bm25_weight=0.4,
        vector_weight=0.6,
        minimum_score=0.0,
        minimum_evidence=2,
    )
    cases = dataset["cases"]
    for _ in range(warmups):
        for case in cases:
            service.search(case["query"], scope, top_k=10, config=config, rerank=False)

    rankings: dict[str, list[str]] = {}
    latencies: list[float] = []
    for repeat in range(repeats):
        for case in cases:
            started = time.perf_counter()
            result = service.search(case["query"], scope, top_k=10, config=config, rerank=False)
            latencies.append((time.perf_counter() - started) * 1000)
            if repeat == 0:
                rankings[case["id"]] = [
                    str(hit.source.get("merchant_id", "")) for hit in result.hits
                ]

    recall, mrr, details = metrics_for_rankings(cases, rankings)
    p95 = percentile_nearest_rank(latencies, 0.95)
    thresholds = {"recall_at_5": 0.80, "mrr_at_10": 0.65, "p95_ms": 300.0}
    passed = {
        "recall_at_5": recall >= thresholds["recall_at_5"],
        "mrr_at_10": mrr >= thresholds["mrr_at_10"],
        "p95_ms": p95 < thresholds["p95_ms"],
    }
    return {
        "task_id": "TK-202-06",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset["dataset_version"],
        "dataset_sha256": dataset_sha256,
        "index": index,
        "embedding_model": "local-deterministic-v1",
        "fusion": {"method": "weighted", "bm25_weight": 0.4, "vector_weight": 0.6},
        "case_count": len(cases),
        "latency_sample_count": len(latencies),
        "warmups": warmups,
        "repeats": repeats,
        "metrics": {
            "recall_at_5": recall,
            "mrr_at_10": mrr,
            "p95_ms": p95,
            "mean_ms": statistics.fmean(latencies),
        },
        "thresholds": thresholds,
        "passed": passed,
        "overall_passed": all(passed.values()),
        "cases": details,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    metrics, passed = report["metrics"], report["passed"]

    def status(value):
        return "PASS" if value else "FAIL"

    lines = [
        "# TK-202-06 检索评测报告",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 数据集：`{report['dataset_version']}`",
        f"- SHA-256：`{report['dataset_sha256']}`",
        f"- 隔离索引：`{report['index']}`（演示数据规模）",
        f"- 查询数 / 延迟样本数：{report['case_count']} / {report['latency_sample_count']}",
        "- P95 口径：生产 `HybridSearchService.search` 墙钟耗时，包含查询 Embedding、BM25+k-NN 双路召回与融合；不包含 HTTP、鉴权和 LLM。",  # noqa: E501
        "",
        "| 指标 | 实测 | 验收阈值 | 结果 |",
        "| --- | ---: | ---: | --- |",
        f"| Recall@5 | {metrics['recall_at_5']:.4f} | ≥ 0.80 | {status(passed['recall_at_5'])} |",
        f"| MRR@10 | {metrics['mrr_at_10']:.4f} | ≥ 0.65 | {status(passed['mrr_at_10'])} |",
        f"| P95 | {metrics['p95_ms']:.3f} ms | < 300 ms | {status(passed['p95_ms'])} |",
        "",
        f"总体结论：**{status(report['overall_passed'])}**。",
        "",
        "## 逐题结果",
        "",
        "| ID | Recall@5 | RR@10 | Top 3 merchant_id |",
        "| --- | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        top3 = ", ".join(case["returned_merchant_ids"][:3])
        lines.append(
            f"| {case['id']} | {case['recall_at_5']:.2f} | "
            f"{case['reciprocal_rank_at_10']:.2f} | {top3} |"
        )
    return "\n".join(lines) + "\n"


def write_reports(report: Mapping[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--opensearch-url", default=os.getenv("OPENSEARCH_URL", "http://127.0.0.1:19200")
    )
    parser.add_argument("--index", default="local-life-search-eval-v1")
    parser.add_argument("--dimension", type=int, default=512)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--prepare-index", action="store_true")
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats <= 0 or args.warmups < 0:
        raise ValueError("repeats must be positive and warmups must be non-negative")
    dataset, checksum = load_dataset(args.dataset)
    embedder = BatchedEmbedder(
        DeterministicEmbeddingProvider(args.dimension), dimension=args.dimension, batch_size=32
    )
    client = OpenSearch(args.opensearch_url)
    try:
        if args.prepare_index:
            prepare_index(
                client,
                index=args.index,
                dataset=dataset,
                dataset_sha256=checksum,
                embedder=embedder,
                dimension=args.dimension,
            )
        if not client.indices.exists(index=args.index):
            raise RuntimeError("evaluation index is absent; run once with --prepare-index")
        report = evaluate(
            client,
            index=args.index,
            dataset=dataset,
            dataset_sha256=checksum,
            embedder=embedder,
            repeats=args.repeats,
            warmups=args.warmups,
        )
        write_reports(report, args.report_json, args.report_md)
    finally:
        client.close()
    print(render_markdown(report))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
