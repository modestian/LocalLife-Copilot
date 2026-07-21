"""TK-502-01 单元测试：LoRA 配置、产物目录、ModelAdapter 和状态枚举。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.infrastructure.models import ModelAdapter
from app.infrastructure.models.enums import (
    DATASET_STATUSES,
    DEPLOYABLE_STATUSES,
    DEPLOYMENT_STATUSES,
    JOB_STATUSES,
    MODEL_VERSION_STATUSES,
    TRAINABLE_DATASET_STATUSES,
)
from training.lora_config import (
    ALLOWED_TASK_TYPES,
    ARTIFACT_ROOT,
    ARTIFACT_SUBDIRS,
    BASE_MODEL_WHITELIST,
    DEFAULT_LORA_ALPHA,
    DEFAULT_LORA_DROPOUT,
    DEFAULT_LORA_R,
    DEFAULT_SEED,
    TRAINING_METHODS,
    LoRAHyperparameters,
    SmokeTestConfig,
    TrainingConfig,
    ensure_artifact_dirs,
    get_artifact_dir,
)

# ── LoRAHyperparameters 测试 ──────────────────────────────────


class TestLoRAHyperparameters:
    def test_defaults_match_design_spec(self):
        """默认值必须与具体设计 §9.3 一致。"""
        hp = LoRAHyperparameters()
        assert hp.r == DEFAULT_LORA_R == 8
        assert hp.lora_alpha == DEFAULT_LORA_ALPHA == 16
        assert hp.lora_dropout == DEFAULT_LORA_DROPOUT == 0.05
        assert hp.learning_rate == 2e-4
        assert hp.epochs == 3
        assert hp.batch_size == 16
        assert hp.seed == DEFAULT_SEED == 42

    def test_api_spec_field_names(self):
        """字段名必须与 API 规范 §8.2 的 JSON key 完全一致。"""
        hp = LoRAHyperparameters()
        dump = hp.model_dump()
        assert set(dump.keys()) == {
            "r",
            "lora_alpha",
            "lora_dropout",
            "learning_rate",
            "epochs",
            "batch_size",
            "seed",
        }

    def test_r_must_be_positive(self):
        with pytest.raises(ValueError, match="r"):
            LoRAHyperparameters(r=0)

    def test_r_upper_bound(self):
        with pytest.raises(ValueError, match="r"):
            LoRAHyperparameters(r=65)

    def test_dropout_must_be_below_half(self):
        with pytest.raises(ValueError, match="lora_dropout"):
            LoRAHyperparameters(lora_dropout=0.5)

    def test_learning_rate_must_be_positive(self):
        with pytest.raises(ValueError, match="learning_rate"):
            LoRAHyperparameters(learning_rate=0)

    def test_learning_rate_upper_bound(self):
        with pytest.raises(ValueError, match="learning_rate"):
            LoRAHyperparameters(learning_rate=0.02)

    def test_to_hash_is_deterministic(self):
        """相同超参产生相同哈希，满足幂等去重要求。"""
        hp1 = LoRAHyperparameters()
        hp2 = LoRAHyperparameters()
        assert hp1.to_hash() == hp2.to_hash()

    def test_to_hash_differs_for_different_params(self):
        hp1 = LoRAHyperparameters(r=8)
        hp2 = LoRAHyperparameters(r=16)
        assert hp1.to_hash() != hp2.to_hash()

    def test_to_hash_is_sha256_hex(self):
        hp = LoRAHyperparameters()
        h = hp.to_hash()
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── TrainingConfig 测试 ───────────────────────────────────────


class TestTrainingConfig:
    def _valid_kwargs(self) -> dict:
        return {
            "task_type": "sentiment_classification",
            "base_model_id": "uer/roberta-base-finetuned-dianping-chinese",
            "dataset_id": "0190c4d2-0000-7000-8000-000000000001",
        }

    def test_valid_config(self):
        cfg = TrainingConfig(**self._valid_kwargs())
        assert cfg.method == "LORA"
        assert cfg.hyperparameters.r == 8

    def test_base_model_whitelist_rejects_unknown(self):
        kwargs = self._valid_kwargs()
        kwargs["base_model_id"] = "gpt-4"
        with pytest.raises(ValueError, match="whitelist"):
            TrainingConfig(**kwargs)

    def test_method_case_insensitive(self):
        kwargs = self._valid_kwargs()
        kwargs["method"] = "lora"
        cfg = TrainingConfig(**kwargs)
        assert cfg.method == "LORA"

    def test_method_rejects_unknown(self):
        kwargs = self._valid_kwargs()
        kwargs["method"] = "PROMPT_TUNING"
        with pytest.raises(ValueError, match="method"):
            TrainingConfig(**kwargs)

    def test_task_type_rejects_unknown(self):
        kwargs = self._valid_kwargs()
        kwargs["task_type"] = "text_generation"
        with pytest.raises(ValueError, match="task_type"):
            TrainingConfig(**kwargs)

    def test_hyperparameters_override(self):
        kwargs = self._valid_kwargs()
        kwargs["hyperparameters"] = LoRAHyperparameters(r=16, lora_alpha=32)
        cfg = TrainingConfig(**kwargs)
        assert cfg.hyperparameters.r == 16
        assert cfg.hyperparameters.lora_alpha == 32


# ── SmokeTestConfig 测试 ───────────────────────────────────────


class TestSmokeTestConfig:
    def test_defaults(self):
        cfg = SmokeTestConfig()
        assert cfg.max_train_samples == 10
        assert cfg.max_eval_samples == 5
        assert cfg.epochs == 1
        assert cfg.batch_size == 2
        assert cfg.seed == DEFAULT_SEED
        assert cfg.expected_min_accuracy == 0.0

    def test_seed_consistent_with_training(self):
        """smoke seed 默认值必须与正式训练一致（验收准则①可重复性）。"""
        smoke = SmokeTestConfig()
        train = LoRAHyperparameters()
        assert smoke.seed == train.seed

    def test_epochs_upper_bound(self):
        with pytest.raises(ValueError):
            SmokeTestConfig(epochs=4)


# ── 产物目录测试 ──────────────────────────────────────────────


class TestArtifactDirs:
    def test_get_artifact_dir_path(self):
        path = get_artifact_dir("job-001")
        assert path == ARTIFACT_ROOT / "job-001"

    def test_ensure_artifact_dirs_creates_all_subdirs(self, tmp_path):
        """ensure_artifact_dirs 应创建所有子目录。"""
        import training.lora_config as mod

        original_root = mod.ARTIFACT_ROOT
        mod.ARTIFACT_ROOT = tmp_path / "artifacts"
        try:
            dirs = ensure_artifact_dirs("test-job")
            assert set(dirs.keys()) == set(ARTIFACT_SUBDIRS)
            for name, path in dirs.items():
                assert path.is_dir(), f"{name} directory not created"
        finally:
            mod.ARTIFACT_ROOT = original_root

    def test_artifact_subdirs_match_design(self):
        """子目录必须覆盖具体设计 §9.3 要求的所有产物。"""
        expected = {"adapter", "tokenizer", "checkpoints", "logs", "config", "model_card"}
        assert set(ARTIFACT_SUBDIRS) == expected


# ── ModelAdapter Protocol 测试 ─────────────────────────────────


class TestModelAdapterProtocol:
    def test_classifier_adapter_satisfies_protocol(self):
        """实现 predict(batch) + model_version 的适配器满足 ModelAdapter 协议。

        具体设计 §9.5：Model Adapter 接口统一 predict(batch)。
        现有 SentimentClassifier 使用 predict_batch + 返回 SentimentResult，
        后续 TK-502-05 将用薄适配器层桥接到 predict(batch) -> list[dict]。
        """

        class _FakeAdapter:
            @property
            def model_version(self) -> str:
                return "test@v1"

            def predict(self, batch: list[str]) -> list[dict]:
                return [{"label": "POSITIVE", "score": 0.9} for _ in batch]

        adapter = _FakeAdapter()
        assert isinstance(adapter, ModelAdapter)

    def test_mock_satisfies_protocol(self):
        """验证 runtime_checkable 可以检测鸭子类型。"""
        mock = MagicMock()
        mock.model_version = "test@v1"
        mock.predict = lambda batch: [{"label": "POSITIVE", "score": 0.9}]
        assert isinstance(mock, ModelAdapter)

    def test_missing_method_fails_protocol(self):
        mock = MagicMock()
        mock.model_version = "test@v1"
        # 没有 predict 方法
        del mock.predict
        assert not isinstance(mock, ModelAdapter)


# ── 状态枚举测试 ──────────────────────────────────────────────


class TestStatusEnums:
    def test_model_version_statuses_match_db_constraint(self):
        """状态值必须与数据库约束 §11.8 的 CHECK 约束一致。"""
        assert MODEL_VERSION_STATUSES == frozenset(
            {"REGISTERED", "EVALUATED", "APPROVED", "REJECTED", "ARCHIVED"}
        )

    def test_only_approved_is_deployable(self):
        """只有 APPROVED 版本可部署。"""
        assert DEPLOYABLE_STATUSES == frozenset({"APPROVED"})

    def test_deployment_statuses(self):
        assert DEPLOYMENT_STATUSES == frozenset({"ACTIVE", "CANARY", "SUPERSEDED", "ROLLED_BACK"})

    def test_job_statuses_match_db_constraint(self):
        assert JOB_STATUSES == frozenset({"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"})

    def test_dataset_statuses(self):
        assert DATASET_STATUSES == frozenset({"BUILDING", "READY", "REJECTED", "ARCHIVED"})

    def test_only_ready_dataset_is_trainable(self):
        assert TRAINABLE_DATASET_STATUSES == frozenset({"READY"})

    def test_base_model_whitelist_not_empty(self):
        assert len(BASE_MODEL_WHITELIST) >= 1
        assert "uer/roberta-base-finetuned-dianping-chinese" in BASE_MODEL_WHITELIST

    def test_training_methods(self):
        assert TRAINING_METHODS == frozenset({"LORA", "QLORA"})

    def test_allowed_task_types(self):
        assert "sentiment_classification" in ALLOWED_TASK_TYPES
