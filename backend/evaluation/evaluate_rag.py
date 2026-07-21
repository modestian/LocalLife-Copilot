"""TK-301-06 deterministic multi-turn and grounded-RAG evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.contracts import ModelInput, ModelPrediction
from app.agents.generation import CitationPolicy, GroundedRAGGenerator
from app.agents.routing import ConstraintExtractor, IntentRouter, route_after_constraints
from app.agents.types import ChatConstraints, RetrievedChunk

DEFAULT_DATASET = Path(__file__).with_name("rag_benchmark_v1.json")
DEFAULT_REPORT_JSON = Path(__file__).with_name("reports") / "tk-301-06-rag-report.json"
DEFAULT_REPORT_MD = Path(__file__).with_name("reports") / "tk-301-06-rag-report.md"
REQUIRED_CATEGORIES = frozenset({"multi_turn", "citation", "hallucination", "no_result"})
THRESHOLDS = {
    "multi_turn_context_accuracy": 0.90,
    "citation_correctness": 0.95,
    "hallucination_rejection_rate": 0.90,
    "fallback_accuracy": 0.90,
}


class FrozenOutputModel:
    def __init__(self, output: Mapping[str, Any] | None) -> None:
        self.output = output

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        return [
            ModelPrediction(
                text="" if self.output is not None else "not-json",
                structured=self.output,
                model_version="frozen-benchmark-output-v1",
            )
            for _ in batch
        ]


def load_dataset(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("schema_version") != 1:
        raise ValueError("unsupported RAG benchmark schema_version")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("benchmark must contain non-empty cases")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        raise ValueError("every benchmark case must have a non-empty id")
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark case ids must be unique")
    categories = Counter(case.get("category") for case in cases)
    if set(categories) != REQUIRED_CATEGORIES:
        raise ValueError("benchmark must contain exactly the four TK-301-06 categories")
    if any(categories[category] < 5 for category in REQUIRED_CATEGORIES):
        raise ValueError("each benchmark category must contain at least five cases")
    for case in cases:
        _validate_case(case)
    canonical = json.dumps(dataset, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return dataset, hashlib.sha256(canonical).hexdigest()


def _validate_case(case: Mapping[str, Any]) -> None:
    category = case["category"]
    if category == "multi_turn":
        if not isinstance(case.get("turns"), list) or len(case["turns"]) < 2:
            raise ValueError(f"multi-turn case {case['id']} needs at least two turns")
        if not isinstance(case.get("expected_constraints"), dict):
            raise ValueError(f"multi-turn case {case['id']} lacks expected constraints")
        if len(case.get("expected_routes", [])) != len(case["turns"]):
            raise ValueError(f"multi-turn case {case['id']} needs one route per turn")
        return
    chunks = case.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError(f"RAG case {case['id']} chunks must be a list")
    if category in {"citation", "hallucination"} and not isinstance(case.get("model_output"), dict):
        raise ValueError(f"case {case['id']} needs a structured model_output")
    if category == "citation" and not case.get("expected_source_ids"):
        raise ValueError(f"citation case {case['id']} needs expected sources")
    if category in {"hallucination", "no_result"} and not isinstance(
        case.get("expected_fallback_reason"), str
    ):
        raise ValueError(f"case {case['id']} needs an expected fallback reason")


def _constraints_payload(constraints: ChatConstraints) -> dict[str, Any]:
    return {
        "distance_meter_lte": constraints.distance_meter_lte,
        "budget_cent_per_person_lte": constraints.budget_cent_per_person_lte,
        "cuisines": list(constraints.cuisines),
        "atmospheres": list(constraints.atmospheres),
        "scenes": list(constraints.scenes),
        "party_size": constraints.party_size,
        "open_now": constraints.open_now,
    }


def _evaluate_multi_turn(case: Mapping[str, Any]) -> dict[str, Any]:
    router, extractor = IntentRouter(), ConstraintExtractor()
    constraints = ChatConstraints()
    routes: list[str] = []
    summary_parts: list[str] = []
    for query in case["turns"]:
        history_summary = "；".join(summary_parts) or None
        intent = router.classify(
            query, history_summary=history_summary, existing_constraints=constraints
        )
        constraints = extractor.extract(
            query, existing=constraints, history_summary=history_summary
        )
        routes.append(
            route_after_constraints(
                {
                    "conversation_id": case["id"],
                    "user_query": query,
                    "history_summary": history_summary,
                    "intent": intent,
                    "constraints": constraints,
                }
            )
        )
        summary_parts.append(query)
    actual = _constraints_payload(constraints)
    passed = actual == case["expected_constraints"] and routes == case["expected_routes"]
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "expected_constraints": case["expected_constraints"],
        "actual_constraints": actual,
        "expected_routes": case["expected_routes"],
        "actual_routes": routes,
    }


def _chunk(payload: Mapping[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=payload["chunk_id"],
        content=payload["content"],
        score=float(payload["score"]),
        source_location=payload["source_location"],
        merchant_id=payload.get("merchant_id"),
        data_updated_at=payload.get("data_updated_at"),
        metadata=dict(payload.get("metadata", {})),
    )


def _evaluate_generation(case: Mapping[str, Any]) -> tuple[dict[str, Any], int, int]:
    policy_data = case.get("citation_policy", {})
    policy = CitationPolicy(
        min_evidence_score=float(policy_data.get("min_evidence_score", 0.0)),
        min_evidence_count=int(policy_data.get("min_evidence_count", 1)),
        min_text_overlap=float(policy_data.get("min_text_overlap", 0.20)),
    )
    chunks = tuple(_chunk(item) for item in case["chunks"])
    result = GroundedRAGGenerator(
        FrozenOutputModel(case.get("model_output")), citation_policy=policy
    ).generate(
        {
            "conversation_id": case["id"],
            "user_query": case["query"],
            "history_summary": case.get("history_summary"),
            "retrieved_chunks": chunks,
        }
    )
    expected_reason = case.get("expected_fallback_reason")
    expected_ids = list(case.get("expected_source_ids", []))
    actual_ids = [source.evidence_id for source in result.sources]
    correct_sources = 0
    if case["category"] == "citation":
        chunk_by_id = {f"E{index}": item for index, item in enumerate(chunks, 1)}
        for source in result.sources:
            expected = chunk_by_id.get(source.evidence_id or "")
            if (
                expected is not None
                and source.content_snapshot == expected.content
                and source.source_location == expected.source_location
            ):
                correct_sources += 1
        passed = not result.is_fallback and actual_ids == expected_ids
    else:
        passed = result.is_fallback and result.fallback_reason == expected_reason
    detail = {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "expected_fallback_reason": expected_reason,
        "actual_fallback_reason": result.fallback_reason,
        "expected_source_ids": expected_ids,
        "actual_source_ids": actual_ids,
    }
    return detail, correct_sources, len(expected_ids)


def evaluate(dataset: Mapping[str, Any], dataset_sha256: str) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    citation_correct, citation_total = 0, 0
    for case in dataset["cases"]:
        if case["category"] == "multi_turn":
            details.append(_evaluate_multi_turn(case))
        else:
            detail, correct, total = _evaluate_generation(case)
            details.append(detail)
            citation_correct += correct
            citation_total += total
    by_category = {
        category: [item for item in details if item["category"] == category]
        for category in REQUIRED_CATEGORIES
    }
    metrics = {
        "multi_turn_context_accuracy": statistics.fmean(
            item["passed"] for item in by_category["multi_turn"]
        ),
        "citation_correctness": citation_correct / citation_total,
        "hallucination_rejection_rate": statistics.fmean(
            item["passed"] for item in by_category["hallucination"]
        ),
        "fallback_accuracy": statistics.fmean(item["passed"] for item in by_category["no_result"]),
    }
    passed = {name: value >= THRESHOLDS[name] for name, value in metrics.items()}
    return {
        "task_id": "TK-301-06",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_version": dataset["dataset_version"],
        "dataset_sha256": dataset_sha256,
        "case_count": len(details),
        "category_counts": dict(sorted(Counter(item["category"] for item in details).items())),
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "passed": passed,
        "overall_passed": all(passed.values()),
        "cases": details,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    def status(value: bool) -> str:
        return "PASS" if value else "FAIL"

    labels = {
        "multi_turn_context_accuracy": "多轮上下文准确率",
        "citation_correctness": "引用正确率",
        "hallucination_rejection_rate": "幻觉拦截率",
        "fallback_accuracy": "无结果兜底准确率",
    }
    lines = [
        "# TK-301-06 RAG 固定集评测报告",
        "",
        f"- 生成时间：`{report['generated_at']}`",
        f"- 数据集：`{report['dataset_version']}`",
        f"- SHA-256：`{report['dataset_sha256']}`",
        f"- 用例数：{report['case_count']}（每类 5 例）",
        (
            "- 口径：直接执行生产约束抽取、路由、Grounded RAG 与 Citation Verifier；"
            "不调用外部模型或搜索服务。"
        ),
        "",
        "| 指标 | 实测 | 门槛 | 结果 |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, label in labels.items():
        lines.append(
            f"| {label} | {report['metrics'][name]:.4f} | "
            f"≥ {report['thresholds'][name]:.2f} | {status(report['passed'][name])} |"
        )
    lines.extend(
        [
            "",
            f"总体结论：**{status(report['overall_passed'])}**。",
            "",
            "## 逐例结果",
            "",
            "| ID | 类别 | 结果 | 兜底原因 / 引用 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in report["cases"]:
        outcome = case.get("actual_fallback_reason") or ", ".join(case.get("actual_source_ids", []))
        if case["category"] == "multi_turn":
            outcome = " → ".join(case["actual_routes"])
        lines.append(
            f"| {case['id']} | {case['category']} | {status(case['passed'])} | {outcome or '-'} |"
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
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset, checksum = load_dataset(args.dataset)
    report = evaluate(dataset, checksum)
    write_reports(report, args.report_json, args.report_md)
    print(render_markdown(report))
    return 0 if report["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
