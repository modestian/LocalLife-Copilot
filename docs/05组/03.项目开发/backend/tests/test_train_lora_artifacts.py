"""TK-502-03 产物验证测试：验证训练产物的完整性和可重复性。

这些测试检查实际训练运行后产生的产物目录，而非单元测试桩。
如果产物目录不存在则跳过（因为需要实际执行训练才能生成）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ARTIFACT_ROOT = Path(__file__).resolve().parent.parent / "training" / "artifacts"

# 需要的快照字段（验收准则②）
REQUIRED_SNAPSHOT_FIELDS = {
    "training_config",
    "hyperparameter_hash",
    "git_commit",
    "dependencies",
    "metrics",
    "dataset_files",
    "created_at",
    "adapter_sha256",
}

# 产物子目录（具体设计 §9.3）
REQUIRED_SUBDIRS = ("adapter", "tokenizer", "checkpoints", "logs", "config", "model_card")

# 依赖版本键（验收准则①）
REQUIRED_DEP_KEYS = ("torch", "transformers", "peft", "datasets", "scikit-learn", "numpy")

# 训练配置字段（验收准则②）
REQUIRED_CONFIG_FIELDS = (
    "task_type",
    "base_model_id",
    "dataset_id",
    "method",
    "hyperparameters",
)


def _load_snapshot(job_id: str) -> dict | None:
    """加载指定 job_id 的 training_snapshot.json。"""
    path = ARTIFACT_ROOT / job_id / "config" / "training_snapshot.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _job_artifact_dir(job_id: str) -> Path:
    return ARTIFACT_ROOT / job_id


# ── Smoke 可重复性验证（验收准则①）──────────────────────────────


class TestSmokeReproducibility:
    """验证两次 smoke 运行产生相同的 SHA-256（验收准则①）。"""

    @pytest.fixture
    def smoke_snapshots(self):
        s1 = _load_snapshot("smoke-001")
        s2 = _load_snapshot("smoke-002")
        if s1 is None or s2 is None:
            pytest.skip("smoke 产物不存在，需先运行 smoke test")
        return s1, s2

    def test_adapter_sha256_match(self, smoke_snapshots):
        s1, s2 = smoke_snapshots
        assert s1["adapter_sha256"] == s2["adapter_sha256"], (
            "两次 smoke 运行的 adapter_sha256 不一致，可重复性失败"
        )

    def test_hyperparameter_hash_match(self, smoke_snapshots):
        s1, s2 = smoke_snapshots
        assert s1["hyperparameter_hash"] == s2["hyperparameter_hash"]

    def test_git_commit_match(self, smoke_snapshots):
        s1, s2 = smoke_snapshots
        assert s1["git_commit"] == s2["git_commit"]

    def test_dependency_versions_match(self, smoke_snapshots):
        s1, s2 = smoke_snapshots
        assert s1["dependencies"] == s2["dependencies"]


# ── Smoke 产物完整性验证（验收准则②）────────────────────────────


class TestSmokeArtifactCompleteness:
    """验证 smoke 产物包含所有必需文件和目录。"""

    @pytest.fixture
    def smoke_dir(self):
        d = _job_artifact_dir("smoke-001")
        if not d.exists():
            pytest.skip("smoke-001 产物不存在")
        return d

    def test_all_subdirs_exist(self, smoke_dir):
        for name in REQUIRED_SUBDIRS:
            assert (smoke_dir / name).is_dir(), f"缺少子目录: {name}"

    def test_adapter_files_exist(self, smoke_dir):
        adapter_dir = smoke_dir / "adapter"
        assert (adapter_dir / "adapter_config.json").exists()
        assert (adapter_dir / "adapter_model.safetensors").exists()

    def test_tokenizer_files_exist(self, smoke_dir):
        tokenizer_dir = smoke_dir / "tokenizer"
        assert (tokenizer_dir / "tokenizer.json").exists()
        assert (tokenizer_dir / "tokenizer_config.json").exists()

    def test_snapshot_exists(self, smoke_dir):
        assert (smoke_dir / "config" / "training_snapshot.json").exists()

    def test_checkpoint_exists(self, smoke_dir):
        # smoke 模式 1 epoch、batch=2，10 样本 → 5 步 → checkpoint-5
        ckpt_dir = smoke_dir / "checkpoints"
        checkpoints = list(ckpt_dir.glob("checkpoint-*"))
        assert len(checkpoints) >= 1, "应至少有一个 checkpoint"


# ── Smoke 快照字段验证（验收准则②）──────────────────────────────


class TestSmokeSnapshotFields:
    """验证 training_snapshot.json 包含所有必需字段。"""

    @pytest.fixture
    def snapshot(self):
        snap = _load_snapshot("smoke-001")
        if snap is None:
            pytest.skip("smoke-001 快照不存在")
        return snap

    def test_has_all_required_fields(self, snapshot):
        missing = REQUIRED_SNAPSHOT_FIELDS - set(snapshot.keys())
        assert not missing, f"快照缺少字段: {missing}"

    def test_training_config_has_required_fields(self, snapshot):
        cfg = snapshot["training_config"]
        missing = set(REQUIRED_CONFIG_FIELDS) - set(cfg.keys())
        assert not missing, f"training_config 缺少字段: {missing}"

    def test_adapter_sha256_is_64_hex(self, snapshot):
        sha = snapshot["adapter_sha256"]
        assert len(sha) == 64
        int(sha, 16)  # 确保是有效的十六进制

    def test_hyperparameter_hash_is_64_hex(self, snapshot):
        sha = snapshot["hyperparameter_hash"]
        assert len(sha) == 64
        int(sha, 16)

    def test_git_commit_is_valid(self, snapshot):
        commit = snapshot["git_commit"]
        assert commit == "unknown" or len(commit) == 40

    def test_dependencies_has_all_keys(self, snapshot):
        deps = snapshot["dependencies"]
        missing = set(REQUIRED_DEP_KEYS) - set(deps.keys())
        assert not missing, f"dependencies 缺少: {missing}"

    def test_metrics_has_eval_f1_macro(self, snapshot):
        assert "eval_f1_macro" in snapshot["metrics"]

    def test_smoke_mode_is_true(self, snapshot):
        assert snapshot["training_config"]["smoke_mode"] is True

    def test_base_model_is_whitelisted(self, snapshot):
        assert (
            snapshot["training_config"]["base_model_id"]
            == "uer/roberta-base-finetuned-dianping-chinese"
        )

    def test_seed_is_42(self, snapshot):
        assert snapshot["training_config"]["hyperparameters"]["seed"] == 42

    def test_dataset_files_specified(self, snapshot):
        df = snapshot["dataset_files"]
        assert "train" in df
        assert "val" in df
        assert "test" in df

    def test_created_at_is_iso_format(self, snapshot):
        ts = snapshot["created_at"]
        assert "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")


# ── 正式 LoRA 训练产物验证（验收准则②）──────────────────────────


class TestLoRATrainingArtifacts:
    """验证正式 LoRA 训练产物的完整性和快照字段。"""

    @pytest.fixture
    def lora_dir(self):
        d = _job_artifact_dir("lora-001")
        # 训练完成前目录可能已创建但产物未保存，用 snapshot 判断是否完成
        if not (d / "config" / "training_snapshot.json").exists():
            pytest.skip("lora-001 训练尚未完成")
        return d

    @pytest.fixture
    def snapshot(self, lora_dir):
        path = lora_dir / "config" / "training_snapshot.json"
        if not path.exists():
            pytest.skip("lora-001 快照不存在")
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def test_all_subdirs_exist(self, lora_dir):
        for name in REQUIRED_SUBDIRS:
            assert (lora_dir / name).is_dir(), f"缺少子目录: {name}"

    def test_adapter_files_exist(self, lora_dir):
        adapter_dir = lora_dir / "adapter"
        assert (adapter_dir / "adapter_config.json").exists()
        assert (adapter_dir / "adapter_model.safetensors").exists()

    def test_tokenizer_files_exist(self, lora_dir):
        tokenizer_dir = lora_dir / "tokenizer"
        assert (tokenizer_dir / "tokenizer.json").exists()

    def test_checkpoint_exists(self, lora_dir):
        ckpt_dir = lora_dir / "checkpoints"
        checkpoints = list(ckpt_dir.glob("checkpoint-*"))
        assert len(checkpoints) >= 1, "应至少有一个 checkpoint"

    def test_snapshot_has_all_fields(self, snapshot):
        missing = REQUIRED_SNAPSHOT_FIELDS - set(snapshot.keys())
        assert not missing, f"快照缺少字段: {missing}"

    def test_adapter_sha256_is_64_hex(self, snapshot):
        sha = snapshot["adapter_sha256"]
        assert len(sha) == 64
        int(sha, 16)

    def test_smoke_mode_is_false(self, snapshot):
        assert snapshot["training_config"]["smoke_mode"] is False

    def test_method_is_lora(self, snapshot):
        assert snapshot["training_config"]["method"] == "LORA"

    def test_epochs_is_3(self, snapshot):
        assert snapshot["training_config"]["hyperparameters"]["epochs"] == 3

    def test_dependencies_has_all_keys(self, snapshot):
        deps = snapshot["dependencies"]
        missing = set(REQUIRED_DEP_KEYS) - set(deps.keys())
        assert not missing, f"dependencies 缺少: {missing}"

    def test_metrics_has_eval_f1_macro(self, snapshot):
        assert "eval_f1_macro" in snapshot["metrics"]

    def test_metrics_has_eval_accuracy(self, snapshot):
        assert "eval_accuracy" in snapshot["metrics"]


# ── 产物目录排除验证（.gitignore）──────────────────────────────


class TestArtifactsGitignored:
    """验证产物目录已加入 .gitignore，不会被提交到版本控制。"""

    def test_artifacts_in_gitignore(self):
        gitignore_path = ARTIFACT_ROOT.parent.parent.parent / ".gitignore"
        if not gitignore_path.exists():
            pytest.skip(".gitignore 不存在")
        content = gitignore_path.read_text(encoding="utf-8")
        assert "training/artifacts/" in content, (
            ".gitignore 应包含 backend/training/artifacts/ 排除规则"
        )
