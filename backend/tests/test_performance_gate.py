import csv
from pathlib import Path

from performance.contracts import API_STAT_NAME, SEARCH_STAT_NAME, TTFB_STAT_NAME
from performance.gate import evaluate


def _write_stats(path: Path, rows: list[dict[str, object]]) -> None:
    columns = ["Type", "Name", "Request Count", "Failure Count", "95%"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def test_gate_passes_only_when_all_thresholds_and_sample_counts_pass(tmp_path: Path) -> None:
    stats = tmp_path / "locust_stats.csv"
    _write_stats(
        stats,
        [
            _row(API_STAT_NAME, p95=499),
            _row(SEARCH_STAT_NAME, p95=299),
            _row(TTFB_STAT_NAME, p95=2000),
        ],
    )

    results = evaluate(stats, minimum_requests=20)

    assert all(result.passed for result in results)


def test_gate_fails_closed_for_boundary_failures_errors_and_missing_rows(tmp_path: Path) -> None:
    stats = tmp_path / "locust_stats.csv"
    _write_stats(
        stats,
        [
            _row(API_STAT_NAME, p95=500),
            _row(SEARCH_STAT_NAME, p95=250, failures=1),
        ],
    )

    results = {result.name: result for result in evaluate(stats, minimum_requests=20)}

    assert not results[API_STAT_NAME].passed
    assert not results[SEARCH_STAT_NAME].passed
    assert results[TTFB_STAT_NAME].reason == "Locust 统计中缺少该场景"


def test_gate_rejects_an_insufficient_sample(tmp_path: Path) -> None:
    stats = tmp_path / "locust_stats.csv"
    _write_stats(stats, [_row(API_STAT_NAME, p95=100, requests=19)])

    result = evaluate(stats, minimum_requests=20)[0]

    assert not result.passed
    assert "样本数 19 少于 20" in result.reason


def _row(name: str, *, p95: int, requests: int = 20, failures: int = 0) -> dict[str, object]:
    return {
        "Type": "GET",
        "Name": name,
        "Request Count": requests,
        "Failure Count": failures,
        "95%": p95,
    }
