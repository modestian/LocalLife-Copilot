"""Celery runtime for merchant analysis and fine-tuning operational tasks."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.sentiment_classifier import SentimentAnalyzer
from app.application.tasks import TaskStage
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.feedback import DatasetItem
from app.infrastructure.db.models.operations import FineTuningJob, Review
from app.infrastructure.db.models.sentiment import ReviewAnalysis
from app.infrastructure.db.models.tasks import AsyncTask
from app.infrastructure.db.repositories.tasks import SQLAlchemyTaskRepository


class OperationalTaskRuntime:
    """Execute operational jobs while preserving the shared task state machine."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        artifact_root: Path,
        worker_id: str = "operational-worker",
    ) -> None:
        self._session_factory = session_factory
        self._tasks = SQLAlchemyTaskRepository(session_factory)
        self._artifact_root = artifact_root
        self._worker_id = worker_id

    async def run_merchant_analysis(self, task_id: UUID) -> dict[str, object]:
        claim = await self._tasks.claim(task_id, worker_id=self._worker_id)
        if claim is None:
            return {"task_id": str(task_id), "status": "SKIPPED"}
        try:
            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.LOADING, progress=10
            )
            mode, since = await self._analysis_options(task_id)
            reviews = await self._load_reviews(claim.resource_id, mode=mode, since=since)
            if await self._tasks.cancellation_requested(task_id, worker_id=self._worker_id):
                await self._tasks.acknowledge_cancellation(task_id, worker_id=self._worker_id)
                return {"task_id": str(task_id), "status": "CANCELLED"}

            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.CLEANING, progress=35
            )
            analyzer = SentimentAnalyzer()
            results = await asyncio.to_thread(
                analyzer.analyze_batch, [review.content for review in reviews]
            )
            if await self._tasks.cancellation_requested(task_id, worker_id=self._worker_id):
                await self._tasks.acknowledge_cancellation(task_id, worker_id=self._worker_id)
                return {"task_id": str(task_id), "status": "CANCELLED"}

            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.PERSISTING, progress=75
            )
            count = await self._save_review_analyses(
                claim.resource_id, reviews, results, mode=mode, since=since
            )
            result = {
                "merchant_id": str(claim.resource_id),
                "mode": mode,
                "analysed_reviews": count,
                "model_version": analyzer.version,
            }
            await self._tasks.succeed(task_id, worker_id=self._worker_id, result=result)
            return {"task_id": str(task_id), "status": "SUCCEEDED", **result}
        except Exception as exc:
            await self._tasks.fail(
                task_id,
                worker_id=self._worker_id,
                error_code="MERCHANT_ANALYSIS_FAILED",
                error_message=str(exc),
            )
            raise

    async def run_fine_tuning(self, task_id: UUID) -> dict[str, object]:
        claim = await self._tasks.claim(task_id, worker_id=self._worker_id)
        if claim is None:
            return {"task_id": str(task_id), "status": "SKIPPED"}
        job_id = claim.resource_id
        try:
            job = await self._start_fine_tuning_job(job_id)
            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.LOADING, progress=10
            )
            files = await self._materialize_dataset(job.dataset_id, job_id)
            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.CLEANING, progress=25
            )
            log_path = self._artifact_dir(job_id) / "logs" / "training.log"
            command = self._training_command(job, files)
            completed = await self._run_command(task_id, command, log_path)
            if not completed:
                return {"task_id": str(task_id), "status": "CANCELLED"}

            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.VERIFYING, progress=90
            )
            artifact_dir = self._artifact_dir(job_id) / "adapter"
            artifact_sha256 = await asyncio.to_thread(_directory_sha256, artifact_dir)
            metrics = _read_training_metrics(
                self._artifact_dir(job_id) / "config" / "training_snapshot.json"
            )
            await self._complete_fine_tuning_job(
                job_id,
                artifact_uri=artifact_dir.resolve().as_uri(),
                artifact_sha256=artifact_sha256,
                log_uri=log_path.resolve().as_uri(),
                metrics=metrics,
            )
            result = {
                "job_id": str(job_id),
                "artifact_uri": artifact_dir.resolve().as_uri(),
                "artifact_sha256": artifact_sha256,
            }
            await self._tasks.succeed(task_id, worker_id=self._worker_id, result=result)
            return {"task_id": str(task_id), "status": "SUCCEEDED", **result}
        except Exception as exc:
            await self._fail_fine_tuning_job(job_id)
            await self._tasks.fail(
                task_id,
                worker_id=self._worker_id,
                error_code="FINE_TUNING_FAILED",
                error_message=str(exc),
            )
            raise

    async def run_evaluation(self, task_id: UUID) -> dict[str, object]:
        claim = await self._tasks.claim(task_id, worker_id=self._worker_id)
        if claim is None:
            return {"task_id": str(task_id), "status": "SKIPPED"}
        job_id = claim.resource_id
        try:
            job = await self._get_fine_tuning_job(job_id)
            benchmark = await self._evaluation_benchmark(task_id)
            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.LOADING, progress=10
            )
            report_dir = self._artifact_dir(job_id) / "evaluation"
            log_path = report_dir / "evaluation.log"
            command = [
                sys.executable,
                "-m",
                "evaluation.evaluate_model",
                "--job-id",
                str(job_id),
                "--base-model",
                job.base_model_ref,
                "--adapter-dir",
                str(self._artifact_dir(job_id) / "adapter"),
                "--tokenizer-dir",
                str(self._artifact_dir(job_id) / "tokenizer"),
                "--test-file",
                str(self._artifact_dir(job_id) / "dataset" / "test.jsonl"),
                "--output-dir",
                str(report_dir),
                "--skip-human-review",
            ]
            completed = await self._run_command(task_id, command, log_path)
            if not completed:
                return {"task_id": str(task_id), "status": "CANCELLED"}
            await self._tasks.heartbeat(
                task_id, worker_id=self._worker_id, stage=TaskStage.VERIFYING, progress=90
            )
            report = _read_json(report_dir / "evaluation_report.json")
            gate = _read_json(report_dir / "publishing_gate_result.json")
            passed = bool(gate.get("passed", gate.get("decision") == "APPROVED"))
            evaluation = {
                "benchmark": benchmark,
                "passed": passed,
                "report_uri": (report_dir / "evaluation_report.json").resolve().as_uri(),
                "gate": gate,
                "metrics": report.get("lora", {}),
            }
            await self._complete_evaluation(job_id, evaluation)
            await self._tasks.succeed(task_id, worker_id=self._worker_id, result=evaluation)
            return {"task_id": str(task_id), "status": "SUCCEEDED", **evaluation}
        except Exception as exc:
            await self._tasks.fail(
                task_id,
                worker_id=self._worker_id,
                error_code="MODEL_EVALUATION_FAILED",
                error_message=str(exc),
            )
            raise

    async def _analysis_options(self, task_id: UUID) -> tuple[str, datetime | None]:
        async with self._session_factory() as session:
            task = await session.get(AsyncTask, task_id)
            values = task.result_json if task and task.result_json else {}
            raw_since = values.get("since")
            return str(values.get("mode") or "INCREMENTAL"), _parse_datetime(raw_since)

    async def _evaluation_benchmark(self, task_id: UUID) -> str:
        async with self._session_factory() as session:
            task = await session.get(AsyncTask, task_id)
            values = task.result_json if task and task.result_json else {}
            return str(values.get("benchmark") or "fixed-test-v1")

    async def _load_reviews(
        self, merchant_id: UUID, *, mode: str, since: datetime | None
    ) -> list[Review]:
        filters = [Review.merchant_id == merchant_id, Review.status == "PUBLISHED"]
        if mode == "INCREMENTAL" and since is not None:
            filters.append(Review.reviewed_at >= since)
        async with self._session_factory() as session:
            return list((await session.scalars(select(Review).where(*filters))).all())

    async def _save_review_analyses(
        self,
        merchant_id: UUID,
        reviews: Sequence[Review],
        results: Sequence[object],
        *,
        mode: str,
        since: datetime | None,
    ) -> int:
        async with self._session_factory() as session, session.begin():
            statement = delete(ReviewAnalysis).where(ReviewAnalysis.merchant_id == str(merchant_id))
            if mode == "INCREMENTAL" and since is not None:
                statement = statement.where(ReviewAnalysis.review_date >= since)
            await session.execute(statement)
            for review, result in zip(reviews, results, strict=True):
                session.add(
                    ReviewAnalysis(
                        merchant_id=str(merchant_id),
                        review_text=review.content,
                        sentiment=result.sentiment,
                        confidence=result.confidence,
                        model_version=result.model_version,
                        aspect_labels=json.dumps(result.aspect_labels, ensure_ascii=False),
                        negative_reasons=json.dumps(result.negative_reason, ensure_ascii=False),
                        review_date=review.reviewed_at,
                    )
                )
            return len(reviews)

    async def _start_fine_tuning_job(self, job_id: UUID) -> FineTuningJob:
        async with self._session_factory() as session, session.begin():
            job = await session.get(FineTuningJob, job_id, with_for_update=True)
            if job is None:
                raise LookupError("fine-tuning job not found")
            if job.status == "CANCELLED":
                raise RuntimeError("fine-tuning job was cancelled")
            job.status = "RUNNING"
            return job

    async def _get_fine_tuning_job(self, job_id: UUID) -> FineTuningJob:
        async with self._session_factory() as session:
            job = await session.get(FineTuningJob, job_id)
            if job is None:
                raise LookupError("fine-tuning job not found")
            if job.status != "SUCCEEDED" or not job.artifact_uri:
                raise RuntimeError("fine-tuning job has no successful artifact")
            return job

    async def _materialize_dataset(self, dataset_id: UUID, job_id: UUID) -> dict[str, Path]:
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(DatasetItem)
                        .where(DatasetItem.dataset_id == dataset_id)
                        .order_by(DatasetItem.id)
                    )
                ).all()
            )
        grouped: dict[str, list[dict[str, object]]] = {"train": [], "validation": [], "test": []}
        for row in rows:
            grouped[row.split].append(dict(row.content_json))
        missing = [name for name, values in grouped.items() if not values]
        if missing:
            raise RuntimeError(f"dataset is missing persisted split items: {', '.join(missing)}")
        dataset_dir = self._artifact_dir(job_id) / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        files: dict[str, Path] = {}
        for split, records in grouped.items():
            path = dataset_dir / f"{split}.jsonl"
            path.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
                encoding="utf-8",
            )
            files[split] = path
        return files

    def _training_command(self, job: FineTuningJob, files: dict[str, Path]) -> list[str]:
        hp = job.hyperparameters_json
        return [
            sys.executable,
            "-m",
            "training.train_lora",
            "--job-id",
            str(job.id),
            "--base-model",
            job.base_model_ref,
            "--dataset-id",
            str(job.dataset_id),
            "--task-type",
            job.task_type,
            "--method",
            job.method,
            "--train-file",
            str(files["train"]),
            "--val-file",
            str(files["validation"]),
            "--test-file",
            str(files["test"]),
            "--r",
            str(hp["r"]),
            "--lora-alpha",
            str(hp["lora_alpha"]),
            "--lora-dropout",
            str(hp["lora_dropout"]),
            "--learning-rate",
            str(hp["learning_rate"]),
            "--epochs",
            str(hp["epochs"]),
            "--batch-size",
            str(hp["batch_size"]),
            "--seed",
            str(hp["seed"]),
        ]

    async def _run_command(self, task_id: UUID, command: list[str], log_path: Path) -> bool:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = {**os.environ, "TRAINING_ARTIFACT_ROOT": str(self._artifact_root)}
        with log_path.open("wb") as log_file:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
            while process.returncode is None:
                if await self._tasks.cancellation_requested(task_id, worker_id=self._worker_id):
                    process.terminate()
                    await process.wait()
                    await self._tasks.acknowledge_cancellation(task_id, worker_id=self._worker_id)
                    return False
                await asyncio.sleep(1)
                await self._tasks.heartbeat(
                    task_id, worker_id=self._worker_id, stage=TaskStage.CLEANING, progress=60
                )
            if process.returncode != 0:
                raise RuntimeError(
                    f"command failed with exit code {process.returncode}; see {log_path}"
                )
        return True

    async def _complete_fine_tuning_job(
        self,
        job_id: UUID,
        *,
        artifact_uri: str,
        artifact_sha256: str,
        log_uri: str,
        metrics: dict[str, object],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            job = await session.get(FineTuningJob, job_id, with_for_update=True)
            if job is None:
                raise LookupError("fine-tuning job not found")
            job.status = "SUCCEEDED"
            job.artifact_uri = artifact_uri
            job.artifact_sha256 = artifact_sha256
            job.log_uri = log_uri
            job.metrics_json = metrics
            job.completed_at = utc_now()

    async def _fail_fine_tuning_job(self, job_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            job = await session.get(FineTuningJob, job_id, with_for_update=True)
            if job is not None and job.status != "CANCELLED":
                job.status = "FAILED"
                job.completed_at = utc_now()

    async def _complete_evaluation(self, job_id: UUID, evaluation: dict[str, object]) -> None:
        async with self._session_factory() as session, session.begin():
            job = await session.get(FineTuningJob, job_id, with_for_update=True)
            if job is None:
                raise LookupError("fine-tuning job not found")
            job.evaluation_json = evaluation

    def _artifact_dir(self, job_id: UUID) -> Path:
        return self._artifact_root / str(job_id)


def _directory_sha256(path: Path) -> str:
    from training.utils import compute_dir_sha256

    return compute_dir_sha256(path)


def _read_training_metrics(path: Path) -> dict[str, object]:
    return dict(_read_json(path).get("metrics", {}))


def _read_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        return dict(json.load(handle))


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
