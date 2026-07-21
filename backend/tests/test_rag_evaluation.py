import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "evaluation" / "evaluate_rag.py"
SPEC = importlib.util.spec_from_file_location("evaluate_rag", MODULE_PATH)
assert SPEC and SPEC.loader
evaluate_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_rag)


def test_frozen_rag_dataset_has_balanced_required_categories() -> None:
    dataset, checksum = evaluate_rag.load_dataset(evaluate_rag.DEFAULT_DATASET)

    assert dataset["dataset_version"] == "tk-301-06-v1"
    assert len(dataset["cases"]) == 20
    assert len(checksum) == 64
    assert {case["category"] for case in dataset["cases"]} == evaluate_rag.REQUIRED_CATEGORIES


def test_frozen_rag_benchmark_passes_all_quality_gates() -> None:
    dataset, checksum = evaluate_rag.load_dataset(evaluate_rag.DEFAULT_DATASET)

    report = evaluate_rag.evaluate(dataset, checksum)

    assert report["overall_passed"] is True
    assert report["metrics"]["citation_correctness"] >= 0.95
    assert report["metrics"]["fallback_accuracy"] >= 0.90
    assert all(case["passed"] for case in report["cases"])


def test_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    dataset, _ = evaluate_rag.load_dataset(evaluate_rag.DEFAULT_DATASET)
    invalid = deepcopy(dataset)
    invalid["cases"][1]["id"] = invalid["cases"][0]["id"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="unique"):
        evaluate_rag.load_dataset(path)
