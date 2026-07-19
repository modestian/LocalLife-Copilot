import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "evaluation" / "evaluate_search.py"
SPEC = importlib.util.spec_from_file_location("evaluate_search", MODULE_PATH)
assert SPEC and SPEC.loader
evaluate_search = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_search)


def test_frozen_dataset_is_valid_and_relevance_targets_exist() -> None:
    dataset, checksum = evaluate_search.load_dataset(evaluate_search.DEFAULT_DATASET)
    assert dataset["dataset_version"] == "tk-202-06-v1"
    assert len(dataset["cases"]) == 20
    assert len(checksum) == 64


def test_recall_at_5_and_mrr_at_10_use_standard_definitions() -> None:
    cases = [
        {"id": "one", "query": "q1", "relevant_merchant_ids": ["a", "b"]},
        {"id": "two", "query": "q2", "relevant_merchant_ids": ["z"]},
    ]
    rankings = {
        "one": ["x", "a", "c", "d", "e", "b"],
        "two": ["x", "y", "z"],
    }
    recall, mrr, details = evaluate_search.metrics_for_rankings(cases, rankings)
    assert recall == pytest.approx(0.75)
    assert mrr == pytest.approx((1 / 2 + 1 / 3) / 2)
    assert details[0]["recall_at_5"] == 0.5


def test_p95_uses_nearest_rank_definition() -> None:
    assert evaluate_search.percentile_nearest_rank(list(range(1, 101)), 0.95) == 95
