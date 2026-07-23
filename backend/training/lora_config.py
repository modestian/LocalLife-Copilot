"""LoRA 训练配置、产物目录和 smoke test 配置定义。

符合具体设计 §9.3 和 API 规范 §8.2 的参数结构。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

# ── 基础模型白名单 ──────────────────────────────────────────────
# API 规范 §8.2：训练任务仅允许引用白名单基础模型，禁止前端传任意脚本。
BASE_MODEL_WHITELIST: frozenset[str] = frozenset(
    {
        "uer/roberta-base-finetuned-dianping-chinese",
    }
)

# ── 训练方法枚举 ────────────────────────────────────────────────
TRAINING_METHODS: frozenset[str] = frozenset({"LORA", "QLORA"})

# ── 默认 LoRA 超参（具体设计 §9.3）─────────────────────────────
DEFAULT_LORA_R = 8
DEFAULT_LORA_ALPHA = 16
DEFAULT_LORA_DROPOUT = 0.05
DEFAULT_LEARNING_RATE = 2e-4
DEFAULT_EPOCHS = 3
DEFAULT_BATCH_SIZE = 16
DEFAULT_SEED = 42

# ── 训练任务类型 ────────────────────────────────────────────────
ALLOWED_TASK_TYPES: frozenset[str] = frozenset(
    {
        "sentiment_classification",
        "negative_reason_attribution",
    }
)

# ── 产物目录结构 ────────────────────────────────────────────────
# 具体设计 §9.3：保存 Adapter、Tokenizer、训练参数、依赖版本、
# Git commit、曲线和 Model Card。
ARTIFACT_ROOT = Path(os.getenv("TRAINING_ARTIFACT_ROOT", "backend/training/artifacts"))

# 单次训练产物子目录名
ARTIFACT_SUBDIRS: tuple[str, ...] = (
    "adapter",  # LoRA Adapter 权重
    "tokenizer",  # Tokenizer 配置
    "checkpoints",  # 训练 checkpoint
    "logs",  # 训练日志和曲线
    "config",  # 训练参数快照 JSON
    "model_card",  # 模型卡
)


def get_artifact_dir(job_id: str) -> Path:
    """获取指定训练任务的产物根目录。

    目录结构：backend/training/artifacts/{job_id}/
    """
    return ARTIFACT_ROOT / job_id


def ensure_artifact_dirs(job_id: str) -> dict[str, Path]:
    """创建训练产物子目录并返回名称到路径的映射。

    返回示例::

        {
            "adapter": Path(".../artifacts/job-1/adapter"),
            "tokenizer": Path(".../artifacts/job-1/tokenizer"),
            ...
        }
    """
    base = get_artifact_dir(job_id)
    dirs = {name: base / name for name in ARTIFACT_SUBDIRS}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


class LoRAHyperparameters(BaseModel):
    """LoRA 超参数，与 API 规范 §8.2 的 hyperparameters 结构对齐。"""

    r: int = Field(default=DEFAULT_LORA_R, ge=1, le=64, description="LoRA 秩")
    lora_alpha: int = Field(default=DEFAULT_LORA_ALPHA, ge=1, description="LoRA alpha 缩放因子")
    lora_dropout: float = Field(
        default=DEFAULT_LORA_DROPOUT,
        ge=0.0,
        lt=0.5,
        description="LoRA dropout 概率",
    )
    learning_rate: float = Field(
        default=DEFAULT_LEARNING_RATE,
        gt=0,
        le=1e-2,
        description="学习率",
    )
    epochs: int = Field(default=DEFAULT_EPOCHS, ge=1, le=20, description="训练轮数")
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=128, description="每设备批大小")
    seed: int = Field(default=DEFAULT_SEED, ge=0, description="随机种子")

    def to_hash(self) -> str:
        """生成超参数的 SHA-256 哈希，用于幂等去重。

        数据库约束 §4.5 fine_tuning_jobs 要求保存 hyperparameter_hash。
        """
        canonical = json.dumps(
            self.model_dump(),
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TrainingConfig(BaseModel):
    """完整训练配置，包含基础模型、数据集、方法和超参。

    对应 API 规范 §8.2 POST /api/v1/fine-tuning/jobs 请求体。
    """

    task_type: str = Field(description="训练任务类型")
    base_model_id: str = Field(description="基础模型 ID，必须在白名单中")
    dataset_id: str = Field(description="已固化的数据集 ID")
    method: str = Field(default="LORA", description="训练方法：LORA 或 QLORA")
    hyperparameters: LoRAHyperparameters = Field(default_factory=LoRAHyperparameters)

    @field_validator("base_model_id")
    @classmethod
    def validate_base_model(cls, value: str) -> str:
        if value not in BASE_MODEL_WHITELIST:
            raise ValueError(f"base_model_id must be in whitelist: {sorted(BASE_MODEL_WHITELIST)}")
        return value

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        upper = value.upper()
        if upper not in TRAINING_METHODS:
            raise ValueError(f"method must be one of {sorted(TRAINING_METHODS)}")
        return upper

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, value: str) -> str:
        if value not in ALLOWED_TASK_TYPES:
            raise ValueError(f"task_type must be one of {sorted(ALLOWED_TASK_TYPES)}")
        return value


class SmokeTestConfig(BaseModel):
    """CPU smoke test 配置，用于快速验证训练管线可重复性。

    验收准则①要求：固定代码版本、基础模型 revision、数据集 hash、
    随机种子和超参数后可重复运行 CPU smoke test。
    """

    max_train_samples: int = Field(default=10, ge=1, description="smoke 训练样本上限")
    max_eval_samples: int = Field(default=5, ge=1, description="smoke 评估样本上限")
    epochs: int = Field(default=1, ge=1, le=3, description="smoke 训练轮数")
    batch_size: int = Field(default=2, ge=1, le=8, description="smoke 批大小")
    seed: int = Field(
        default=DEFAULT_SEED,
        ge=0,
        description="随机种子，与正式训练保持一致以确保可重复性",
    )
    # smoke 不要求指标达标，只验证管线可运行
    expected_min_accuracy: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="smoke 最低准确率要求，默认为 0 即只验证管线可运行",
    )
