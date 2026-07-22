"""Evaluate Locust CSV statistics against the TK-703-03 release thresholds."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from performance.contracts import API_STAT_NAME, SEARCH_STAT_NAME, TTFB_STAT_NAME


@dataclass(frozen=True, slots=True)
class GateRule:
    name: str
    threshold_ms: float
    inclusive: bool


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    requests: int
    failures: int
    p95_ms: float | None
    threshold_ms: float
    comparison: str
    passed: bool
    reason: str


RULES: Final = (
    GateRule(API_STAT_NAME, 500.0, False),
    GateRule(SEARCH_STAT_NAME, 300.0, False),
    GateRule(TTFB_STAT_NAME, 2000.0, True),
)


def evaluate(stats_csv: Path, *, minimum_requests: int) -> list[GateResult]:
    with stats_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["Name"]: row for row in csv.DictReader(handle)}

    results: list[GateResult] = []
    for rule in RULES:
        row = rows.get(rule.name)
        if row is None:
            results.append(_missing_result(rule))
            continue
        requests = _integer(row, "Request Count")
        failures = _integer(row, "Failure Count")
        p95_ms = _number(row, "95%")
        comparison = "≤" if rule.inclusive else "<"
        latency_passed = p95_ms is not None and (
            p95_ms <= rule.threshold_ms if rule.inclusive else p95_ms < rule.threshold_ms
        )
        reasons = []
        if requests < minimum_requests:
            reasons.append(f"样本数 {requests} 少于 {minimum_requests}")
        if failures:
            reasons.append(f"存在 {failures} 个失败请求")
        if p95_ms is None:
            reasons.append("缺少 P95")
        elif not latency_passed:
            reasons.append(f"P95 {p95_ms:g} ms 未满足 {comparison} {rule.threshold_ms:g} ms")
        passed = requests >= minimum_requests and failures == 0 and latency_passed
        results.append(
            GateResult(
                name=rule.name,
                requests=requests,
                failures=failures,
                p95_ms=p95_ms,
                threshold_ms=rule.threshold_ms,
                comparison=comparison,
                passed=passed,
                reason="通过" if passed else "；".join(reasons),
            )
        )
    return results


def write_reports(
    results: list[GateResult],
    *,
    json_path: Path,
    markdown_path: Path,
    source_csv: Path,
    minimum_requests: int,
) -> None:
    generated_at = datetime.now(UTC).isoformat()
    passed = all(result.passed for result in results)
    payload = {
        "task_id": "TK-703-03",
        "generated_at": generated_at,
        "source_csv": str(source_csv),
        "minimum_requests_per_metric": minimum_requests,
        "passed": passed,
        "results": [asdict(result) for result in results],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(
        _markdown(payload, results),
        encoding="utf-8",
    )


def _markdown(payload: dict[str, object], results: list[GateResult]) -> str:
    lines = [
        "# TK-703-03 Locust 性能门禁结果",
        "",
        f"- 生成时间：`{payload['generated_at']}`",
        f"- 原始统计：`{payload['source_csv']}`",
        f"- 每项最小样本数：`{payload['minimum_requests_per_metric']}`",
        f"- 总体结论：**{'PASS' if payload['passed'] else 'FAIL'}**",
        "",
        "| 场景 | 样本 | 失败 | P95 | 门槛 | 结果 | 说明 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        p95 = "N/A" if result.p95_ms is None else f"{result.p95_ms:g} ms"
        lines.append(
            f"| {result.name} | {result.requests} | {result.failures} | {p95} | "
            f"{result.comparison} {result.threshold_ms:g} ms | "
            f"{'PASS' if result.passed else 'FAIL'} | {result.reason} |"
        )
    lines.extend(
        [
            "",
            "P95 取自 Locust 聚合统计；流式场景覆盖从请求发出到首个非空 SSE `data:` "
            "帧到达的墙钟耗时。任一场景缺失、样本不足、出现失败或超出延迟门槛，门禁均失败。",
            "",
        ]
    )
    return "\n".join(lines)


def _missing_result(rule: GateRule) -> GateResult:
    return GateResult(
        name=rule.name,
        requests=0,
        failures=0,
        p95_ms=None,
        threshold_ms=rule.threshold_ms,
        comparison="≤" if rule.inclusive else "<",
        passed=False,
        reason="Locust 统计中缺少该场景",
    )


def _integer(row: dict[str, str], column: str) -> int:
    try:
        return int(row.get(column, "0") or 0)
    except ValueError:
        return 0


def _number(row: dict[str, str], column: str) -> float | None:
    try:
        value = row.get(column, "")
        return float(value) if value else None
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stats_csv", type=Path)
    parser.add_argument("--minimum-requests", type=int, default=20)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    if args.minimum_requests < 1:
        parser.error("--minimum-requests must be at least 1")

    results = evaluate(args.stats_csv, minimum_requests=args.minimum_requests)
    write_reports(
        results,
        json_path=args.json,
        markdown_path=args.markdown,
        source_csv=args.stats_csv,
        minimum_requests=args.minimum_requests,
    )
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
