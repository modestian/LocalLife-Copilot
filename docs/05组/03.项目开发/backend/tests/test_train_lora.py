"""TK-502-02 单元测试：LoRA 训练脚本的配置构建、产物工具和配置快照。

不测试实际训练（需要 torch/peft 运行时），只验证可独立测试的逻辑。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from training.lora_config import (
    ARTIFACT_SUBDIRS,
    DEFAULT_SEED,
    LoRAHyperparameters,
    SmokeTestConfig,
    TrainingConfig,
    ensure_artifact_dirs,
)
from training.utils import (
    compute_dir_sha256,
    compute_file_sha256,
    get_dependency_versions,
    get_git_commit,
    save_training_snapshot,
)

# ── 配置构建测试 ───────────────────────────────────────────────


class TestConfigBuilding:
    def test_training_config_defaults(self):
        cfg = TrainingConfig(
            task_type="sentiment_classification",
            base_model_id="uer/roberta-base-finetuned-dianping-chinese",
            dataset_id="test-dataset-001",
        )
        assert cfg.method == "LORA"
        assert cfg.hyperparameters.r == 8
        assert cfg.hyperparameters.lora_alpha == 16
        assert cfg.hyperparameters.lora_dropout == 0.05
        assert cfg.hyperparameters.learning_rate == 2e-4
        assert cfg.hyperparameters.epochs == 3
        assert cfg.hyperparameters.batch_size == 16
        assert cfg.hyperparameters.seed == DEFAULT_SEED

    def test_smoke_config_defaults(self):
        cfg = SmokeTestConfig()
        assert cfg.max_train_samples == 10
        assert cfg.max_eval_samples == 5
        assert cfg.epochs == 1
        assert cfg.batch_size == 2
        assert cfg.seed == DEFAULT_SEED

    def test_smoke_seed_matches_training(self):
        smoke = SmokeTestConfig()
        train = LoRAHyperparameters()
        assert smoke.seed == train.seed

    def test_hyperparameter_hash_in_config(self):
        hp = LoRAHyperparameters()
        TrainingConfig(
            task_type="sentiment_classification",
            base_model_id="uer/roberta-base-finetuned-dianping-chinese",
            dataset_id="test-dataset-001",
            hyperparameters=hp,
        )
        assert hp.to_hash() != ""


# ── SHA-256 哈希测试 ──────────────────────────────────────────


class TestSHA256:
    def test_compute_file_sha256_deterministic(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h1 = compute_file_sha256(f)
        h2 = compute_file_sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_dir_sha256_deterministic(self, tmp_path):
        d = tmp_path / "adapter"
        d.mkdir()
        (d / "adapter_model.safetensors").write_bytes(b"\x00\x01\x02")
        (d / "adapter_config.json").write_text(json.dumps({"r": 8}), encoding="utf-8")
        h1 = compute_dir_sha256(d)
        h2 = compute_dir_sha256(d)
        assert h1 == h2
        assert len(h1) == 64

    def test_compute_dir_sha256_changes_on_content_change(self, tmp_path):
        d = tmp_path / "adapter"
        d.mkdir()
        (d / "weights.bin").write_bytes(b"\x00\x01")
        h1 = compute_dir_sha256(d)
        (d / "weights.bin").write_bytes(b"\x00\x02")
        h2 = compute_dir_sha256(d)
        assert h1 != h2

    def test_compute_dir_sha256_includes_filenames(self, tmp_path):
        d1 = tmp_path / "dir1"
        d1.mkdir()
        (d1 / "a.bin").write_bytes(b"\x00\x01")
        d2 = tmp_path / "dir2"
        d2.mkdir()
        (d2 / "b.bin").write_bytes(b"\x00\x01")
        assert compute_dir_sha256(d1) != compute_dir_sha256(d2)

    def test_compute_dir_sha256_raises_on_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            compute_dir_sha256(tmp_path / "nonexistent")


# ── Git commit 测试 ───────────────────────────────────────────


class TestGitCommit:
    def test_returns_commit_or_unknown(self):
        result = get_git_commit()
        assert result == "unknown" or len(result) == 40

    @patch("training.utils.subprocess.run")
    def test_returns_commit_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123def456\n")
        assert get_git_commit() == "abc123def456"

    @patch("training.utils.subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_git_commit() == "unknown"


# ── 依赖版本测试 ──────────────────────────────────────────────


class TestDependencyVersions:
    def test_returns_dict_with_expected_keys(self):
        versions = get_dependency_versions()
        assert "torch" in versions
        assert "transformers" in versions
        assert "peft" in versions
        assert "datasets" in versions
        assert "scikit-learn" in versions
        assert "numpy" in versions

    def test_missing_dep_returns_not_installed(self):
        versions = get_dependency_versions()
        # peft may not be installed in test environment
        assert versions["peft"] in ("not-installed",) or len(versions["peft"]) > 0


# ── 训练快照测试 ──────────────────────────────────────────────


class TestTrainingSnapshot:
    def test_save_and_read_snapshot(self, tmp_path):
        dirs = {name: tmp_path / name for name in ARTIFACT_SUBDIRS}
        for p in dirs.values():
            p.mkdir(parents=True, exist_ok=True)

        hp = LoRAHyperparameters()
        config_data = {
            "task_type": "sentiment_classification",
            "base_model_id": "uer/roberta-base-finetuned-dianping-chinese",
            "dataset_id": "test-001",
            "method": "LORA",
            "hyperparameters": hp.model_dump(),
        }

        snapshot_path = save_training_snapshot(
            config_data=config_data,
            artifact_dirs=dirs,
            metrics={"eval_f1_macro": 0.85},
            dataset_files={"train": "train.jsonl"},
        )

        assert snapshot_path.exists()
        with snapshot_path.open(encoding="utf-8") as f:
            snapshot = json.load(f)

        assert "training_config" in snapshot
        assert "dependencies" in snapshot
        assert "git_commit" in snapshot
        assert "created_at" in snapshot
        assert snapshot["metrics"]["eval_f1_macro"] == 0.85
        assert snapshot["dataset_files"]["train"] == "train.jsonl"


# ── 产物目录测试 ──────────────────────────────────────────────


class TestArtifactDirsCreation:
    def test_ensure_artifact_dirs_creates_all(self, tmp_path):
        import training.lora_config as mod

        original_root = mod.ARTIFACT_ROOT
        mod.ARTIFACT_ROOT = tmp_path / "artifacts"
        try:
            dirs = ensure_artifact_dirs("test-job-002")
            for name in ARTIFACT_SUBDIRS:
                assert dirs[name].is_dir()
        finally:
            mod.ARTIFACT_ROOT = original_root


# ── train_lora 参数解析测试（不执行训练）─────────────────────


class TestArgParsing:
    def test_parse_args_smoke_mode(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "train_lora.py",
                "--job-id",
                "smoke-test-001",
                "--smoke",
            ],
        )
        from training.train_lora import parse_args

        args = parse_args()
        assert args.job_id == "smoke-test-001"
        assert args.smoke is True
        assert args.r == 8
        assert args.lora_alpha == 16
        assert args.lora_dropout == 0.05
        assert args.learning_rate == 2e-4
        assert args.epochs == 3
        assert args.seed == DEFAULT_SEED

    def test_parse_args_custom_params(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            [
                "train_lora.py",
                "--job-id",
                "lora-custom-001",
                "--r",
                "16",
                "--lora-alpha",
                "32",
                "--learning-rate",
                "0.0003",
                "--epochs",
                "5",
                "--method",
                "QLORA",
            ],
        )
        from training.train_lora import parse_args

        args = parse_args()
        assert args.r == 16
        assert args.lora_alpha == 32
        assert args.learning_rate == 0.0003
        assert args.epochs == 5
        assert args.method == "QLORA"
        assert args.smoke is False

    def test_build_training_config_from_args(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["train_lora.py", "--job-id", "test-001"],
        )
        from training.train_lora import build_training_config, parse_args

        args = parse_args()
        cfg = build_training_config(args)
        assert cfg.task_type == "sentiment_classification"
        assert cfg.base_model_id == "uer/roberta-base-finetuned-dianping-chinese"
        assert cfg.method == "LORA"
        assert cfg.hyperparameters.r == 8

    def test_build_smoke_config_from_args(self, monkeypatch):
        monkeypatch.setattr(
            "sys.argv",
            ["train_lora.py", "--job-id", "test-001", "--smoke"],
        )
        from training.train_lora import build_smoke_config, parse_args

        args = parse_args()
        smoke = build_smoke_config(args)
        assert smoke.max_train_samples == 10
        assert smoke.max_eval_samples == 5
        assert smoke.seed == DEFAULT_SEED


# ── 截断数据集测试 ─────────────────────────────────────────────


class TestTruncateDataset:
    def test_truncate_with_mock_dataset(self):
        from training.train_lora import truncate_dataset

        mock_ds = MagicMock()
        mock_ds.__len__ = lambda self: 100
        mock_ds.select.return_value = "truncated"
        result = truncate_dataset(mock_ds, 10)
        mock_ds.select.assert_called_once_with(range(10))
        assert result == "truncated"

    def test_truncate_returns_original_if_smaller(self):
        from training.train_lora import truncate_dataset

        mock_ds = MagicMock()
        mock_ds.__len__ = lambda self: 5
        result = truncate_dataset(mock_ds, 10)
        mock_ds.select.assert_not_called()
        assert result is mock_ds
