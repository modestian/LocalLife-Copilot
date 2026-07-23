import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.tasks import TaskStage
from app.core.ids import uuid7
from app.operations import task_runtime
from app.operations.task_runtime import OperationalTaskRuntime


def _runtime(tmp_path: Path) -> OperationalTaskRuntime:
    runtime = OperationalTaskRuntime(MagicMock(), artifact_root=tmp_path, worker_id="test-worker")
    runtime._tasks = MagicMock()
    runtime._tasks.claim = AsyncMock()
    runtime._tasks.heartbeat = AsyncMock()
    runtime._tasks.cancellation_requested = AsyncMock(return_value=False)
    runtime._tasks.acknowledge_cancellation = AsyncMock()
    runtime._tasks.succeed = AsyncMock()
    runtime._tasks.fail = AsyncMock()
    return runtime


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "resource_kind"),
    [
        ("run_merchant_analysis", "merchant"),
        ("run_fine_tuning", "job"),
        ("run_evaluation", "job"),
    ],
)
async def test_operational_tasks_skip_when_claim_is_unavailable(
    tmp_path: Path, method_name: str, resource_kind: str
) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    runtime._tasks.claim.return_value = None

    result = await getattr(runtime, method_name)(task_id)

    assert result == {"task_id": str(task_id), "status": "SKIPPED"}
    runtime._tasks.claim.assert_awaited_once_with(task_id, worker_id="test-worker")


@pytest.mark.asyncio
async def test_merchant_analysis_persists_results_and_succeeds(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    merchant_id = uuid7()
    reviews = [SimpleNamespace(content="great"), SimpleNamespace(content="slow")]
    analysis_results = [MagicMock(), MagicMock()]
    analyzer = MagicMock(version="sentiment-v2")
    analyzer.analyze_batch.return_value = analysis_results
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=merchant_id)
    runtime._analysis_options = AsyncMock(return_value=("FULL", None))
    runtime._load_reviews = AsyncMock(return_value=reviews)
    runtime._save_review_analyses = AsyncMock(return_value=2)
    monkeypatch.setattr(task_runtime, "SentimentAnalyzer", MagicMock(return_value=analyzer))

    result = await runtime.run_merchant_analysis(task_id)

    assert result == {
        "task_id": str(task_id),
        "status": "SUCCEEDED",
        "merchant_id": str(merchant_id),
        "mode": "FULL",
        "analysed_reviews": 2,
        "model_version": "sentiment-v2",
    }
    analyzer.analyze_batch.assert_called_once_with(["great", "slow"])
    runtime._save_review_analyses.assert_awaited_once_with(
        merchant_id, reviews, analysis_results, mode="FULL", since=None
    )
    assert [call.kwargs["stage"] for call in runtime._tasks.heartbeat.await_args_list] == [
        TaskStage.LOADING,
        TaskStage.CLEANING,
        TaskStage.PERSISTING,
    ]
    runtime._tasks.succeed.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_check", [1, 2])
async def test_merchant_analysis_acknowledges_cancellation(
    tmp_path: Path, monkeypatch, cancel_check: int
) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=uuid7())
    runtime._analysis_options = AsyncMock(return_value=("INCREMENTAL", None))
    runtime._load_reviews = AsyncMock(return_value=[SimpleNamespace(content="ok")])
    runtime._tasks.cancellation_requested.side_effect = [cancel_check == 1, cancel_check == 2]
    analyzer = MagicMock()
    analyzer.analyze_batch.return_value = [MagicMock()]
    monkeypatch.setattr(task_runtime, "SentimentAnalyzer", MagicMock(return_value=analyzer))

    result = await runtime.run_merchant_analysis(task_id)

    assert result == {"task_id": str(task_id), "status": "CANCELLED"}
    runtime._tasks.acknowledge_cancellation.assert_awaited_once_with(
        task_id, worker_id="test-worker"
    )
    runtime._tasks.succeed.assert_not_awaited()


@pytest.mark.asyncio
async def test_merchant_analysis_records_failure(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=uuid7())
    runtime._analysis_options = AsyncMock(side_effect=ValueError("invalid analysis options"))

    with pytest.raises(ValueError, match="invalid analysis options"):
        await runtime.run_merchant_analysis(task_id)

    runtime._tasks.fail.assert_awaited_once_with(
        task_id,
        worker_id="test-worker",
        error_code="MERCHANT_ANALYSIS_FAILED",
        error_message="invalid analysis options",
    )


@pytest.mark.asyncio
async def test_fine_tuning_completes_artifacts_and_task(tmp_path: Path, monkeypatch) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    job_id = uuid7()
    dataset_id = uuid7()
    job = SimpleNamespace(id=job_id, dataset_id=dataset_id)
    files = {"train": tmp_path / "train.jsonl"}
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=job_id)
    runtime._start_fine_tuning_job = AsyncMock(return_value=job)
    runtime._materialize_dataset = AsyncMock(return_value=files)
    runtime._training_command = MagicMock(return_value=["python", "train.py"])
    runtime._run_command = AsyncMock(return_value=True)
    runtime._complete_fine_tuning_job = AsyncMock()
    monkeypatch.setattr(task_runtime, "_directory_sha256", MagicMock(return_value="abc123"))
    monkeypatch.setattr(
        task_runtime, "_read_training_metrics", MagicMock(return_value={"loss": 0.1})
    )

    result = await runtime.run_fine_tuning(task_id)

    artifact_dir = tmp_path / str(job_id) / "adapter"
    assert result == {
        "task_id": str(task_id),
        "status": "SUCCEEDED",
        "job_id": str(job_id),
        "artifact_uri": artifact_dir.resolve().as_uri(),
        "artifact_sha256": "abc123",
    }
    runtime._complete_fine_tuning_job.assert_awaited_once()
    runtime._tasks.succeed.assert_awaited_once()


@pytest.mark.asyncio
async def test_fine_tuning_returns_cancelled_when_command_is_stopped(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    job_id = uuid7()
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=job_id)
    runtime._start_fine_tuning_job = AsyncMock(
        return_value=SimpleNamespace(id=job_id, dataset_id=uuid7())
    )
    runtime._materialize_dataset = AsyncMock(return_value={})
    runtime._training_command = MagicMock(return_value=["train"])
    runtime._run_command = AsyncMock(return_value=False)

    result = await runtime.run_fine_tuning(task_id)

    assert result == {"task_id": str(task_id), "status": "CANCELLED"}
    runtime._tasks.succeed.assert_not_awaited()


@pytest.mark.asyncio
async def test_fine_tuning_marks_job_and_task_failed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    job_id = uuid7()
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=job_id)
    runtime._start_fine_tuning_job = AsyncMock(side_effect=RuntimeError("training unavailable"))
    runtime._fail_fine_tuning_job = AsyncMock()

    with pytest.raises(RuntimeError, match="training unavailable"):
        await runtime.run_fine_tuning(task_id)

    runtime._fail_fine_tuning_job.assert_awaited_once_with(job_id)
    runtime._tasks.fail.assert_awaited_once_with(
        task_id,
        worker_id="test-worker",
        error_code="FINE_TUNING_FAILED",
        error_message="training unavailable",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gate", "expected_passed"),
    [({"passed": True}, True), ({"decision": "REJECTED"}, False)],
)
async def test_evaluation_records_report_and_gate(
    tmp_path: Path, monkeypatch, gate: dict[str, object], expected_passed: bool
) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    job_id = uuid7()
    job = SimpleNamespace(base_model_ref="base-model")
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=job_id)
    runtime._get_fine_tuning_job = AsyncMock(return_value=job)
    runtime._evaluation_benchmark = AsyncMock(return_value="benchmark-v2")
    runtime._run_command = AsyncMock(return_value=True)
    runtime._complete_evaluation = AsyncMock()

    def read_json(path: Path) -> dict[str, object]:
        if path.name == "evaluation_report.json":
            return {"lora": {"accuracy": 0.9}}
        return gate

    monkeypatch.setattr(task_runtime, "_read_json", read_json)

    result = await runtime.run_evaluation(task_id)

    assert result["status"] == "SUCCEEDED"
    assert result["benchmark"] == "benchmark-v2"
    assert result["passed"] is expected_passed
    assert result["metrics"] == {"accuracy": 0.9}
    runtime._complete_evaluation.assert_awaited_once_with(
        job_id,
        {
            "benchmark": "benchmark-v2",
            "passed": expected_passed,
            "report_uri": (tmp_path / str(job_id) / "evaluation" / "evaluation_report.json")
            .resolve()
            .as_uri(),
            "gate": gate,
            "metrics": {"accuracy": 0.9},
        },
    )
    runtime._tasks.succeed.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluation_handles_cancel_and_failure(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    task_id = uuid7()
    job_id = uuid7()
    runtime._tasks.claim.return_value = SimpleNamespace(resource_id=job_id)
    runtime._get_fine_tuning_job = AsyncMock(
        return_value=SimpleNamespace(base_model_ref="base-model")
    )
    runtime._evaluation_benchmark = AsyncMock(return_value="fixed-test-v1")
    runtime._run_command = AsyncMock(return_value=False)

    assert await runtime.run_evaluation(task_id) == {
        "task_id": str(task_id),
        "status": "CANCELLED",
    }

    runtime._get_fine_tuning_job.side_effect = LookupError("artifact missing")
    with pytest.raises(LookupError, match="artifact missing"):
        await runtime.run_evaluation(task_id)
    runtime._tasks.fail.assert_awaited_once_with(
        task_id,
        worker_id="test-worker",
        error_code="MODEL_EVALUATION_FAILED",
        error_message="artifact missing",
    )


def test_training_command_serializes_job_configuration(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    job = SimpleNamespace(
        id=uuid7(),
        dataset_id=uuid7(),
        base_model_ref="base",
        task_type="reply",
        method="LORA",
        hyperparameters_json={
            "r": 8,
            "lora_alpha": 16,
            "lora_dropout": 0.1,
            "learning_rate": 0.0002,
            "epochs": 3,
            "batch_size": 4,
            "seed": 42,
        },
    )
    files = {
        "train": tmp_path / "train.jsonl",
        "validation": tmp_path / "validation.jsonl",
        "test": tmp_path / "test.jsonl",
    }

    command = runtime._training_command(job, files)

    assert command[:3] == [task_runtime.sys.executable, "-m", "training.train_lora"]
    assert command[command.index("--r") + 1] == "8"
    assert command[command.index("--train-file") + 1] == str(files["train"])
    assert command[command.index("--seed") + 1] == "42"


def test_json_datetime_and_metrics_helpers(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"metrics": {"loss": 0.25}, "passed": True}), encoding="utf-8")

    assert task_runtime._read_json(snapshot)["passed"] is True
    assert task_runtime._read_training_metrics(snapshot) == {"loss": 0.25}
    assert task_runtime._parse_datetime(None) is None
    assert task_runtime._parse_datetime("") is None
    assert task_runtime._parse_datetime("2026-07-23T10:30:00") == datetime(
        2026, 7, 23, 10, 30, tzinfo=UTC
    )
    aware = task_runtime._parse_datetime("2026-07-23T10:30:00+08:00")
    assert aware is not None and aware.utcoffset() is not None
