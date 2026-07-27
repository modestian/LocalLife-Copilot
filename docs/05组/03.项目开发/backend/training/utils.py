"""LoRA 训练辅助工具：SHA-256 哈希、Git commit、依赖版本和配置快照。

具体设计 §9.3：保存 Adapter、Tokenizer、训练参数、依赖版本、Git commit、曲线和 Model Card。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any


def compute_dir_sha256(directory: Path) -> str:
    """递归计算目录内所有文件的 SHA-256 摘要。

    验收准则②要求保存 adapter 的 SHA-256。
    文件按路径排序后逐个读取，确保不同平台和文件系统产生相同哈希。
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")

    files = sorted(p for p in directory.rglob("*") if p.is_file())
    hasher = hashlib.sha256()
    for file_path in files:
        # 将相对路径纳入哈希，确保文件名变更也能被检测
        rel_path = file_path.relative_to(directory).as_posix()
        hasher.update(rel_path.encode("utf-8"))
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def get_git_commit() -> str:
    """获取当前 Git commit hash，失败时返回 'unknown'。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:40]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "unknown"


def get_dependency_versions() -> dict[str, str]:
    """收集训练相关依赖的版本信息。"""
    versions: dict[str, str] = {}

    for pkg_name, import_name in [
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("peft", "peft"),
        ("datasets", "datasets"),
        ("scikit-learn", "sklearn"),
        ("numpy", "numpy"),
    ]:
        try:
            mod = __import__(import_name)
            versions[pkg_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[pkg_name] = "not-installed"

    return versions


def save_training_snapshot(
    config_data: dict[str, Any],
    artifact_dirs: dict[str, Path],
    metrics: dict[str, Any] | None = None,
    dataset_files: dict[str, str] | None = None,
) -> Path:
    """保存训练配置快照 JSON 到 config/ 目录。

    包含：训练配置、超参哈希、Git commit、依赖版本、数据集路径、指标和时间戳。
    """
    snapshot = {
        "training_config": config_data,
        "hyperparameter_hash": config_data.get("hyperparameters", {}).get("to_hash", ""),
        "git_commit": get_git_commit(),
        "dependencies": get_dependency_versions(),
        "metrics": metrics or {},
        "dataset_files": dataset_files or {},
        "created_at": datetime.now(UTC).isoformat(),
    }

    config_path = artifact_dirs["config"] / "training_snapshot.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    return config_path


def compute_file_sha256(file_path: Path) -> str:
    """计算单个文件的 SHA-256。"""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
