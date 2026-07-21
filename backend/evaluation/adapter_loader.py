"""LoRA Adapter 推理加载器。

具体设计 §9.5：Model Adapter 接口统一 predict(batch)；
配置切换只改变注册版本，不让业务代码感知 PEFT 细节。

加载 base model + LoRA adapter 组合，通过 ModelAdapter Protocol
提供与 SentimentClassifier 一致的 predict(batch) 接口，
确保基线和 LoRA 评测使用完全相同的后处理逻辑（factual neutral
检测、margin 校准），差异只来自模型权重。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.analytics.sentiment_classifier import (
    SENTIMENT_LABELS,
    SentimentClassifier,
    _normalize_label,
)

logger = logging.getLogger(__name__)


class LoRAAdapterLoader:
    """加载 base model + LoRA adapter 并提供统一推理接口。

    满足 ModelAdapter Protocol（model_version 属性 + predict(batch) 方法）。
    复用 SentimentClassifier 的 _calibrate_neutral 后处理逻辑，
    确保基线和 LoRA 公平对比。
    """

    def __init__(
        self,
        base_model_id: str,
        adapter_dir: str | Path,
        tokenizer_dir: str | Path | None = None,
        batch_size: int = 32,
    ):
        self.base_model_id = base_model_id
        self.adapter_dir = Path(adapter_dir)
        self.tokenizer_dir = (
            Path(tokenizer_dir) if tokenizer_dir else self.adapter_dir.parent / "tokenizer"
        )
        self.batch_size = batch_size
        self._classifier: SentimentClassifier | None = None
        self._model_version: str | None = None

    @property
    def model_version(self) -> str:
        """返回模型版本标识。"""
        if self._model_version is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._model_version

    def load(self) -> None:
        """加载 base model + LoRA adapter + tokenizer。

        使用 PEFT 的 PeftModel.from_pretrained 将 adapter 叠加到基础模型上，
        然后通过 transformers pipeline 提供推理能力。
        """
        import torch
        from peft import PeftModel
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            pipeline,
        )

        device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            "Loading LoRA adapter: base=%s, adapter=%s, device=%s",
            self.base_model_id,
            self.adapter_dir,
            device,
        )

        # 加载基础模型（num_labels=3，与训练时一致）
        # ignore_mismatched_sizes=True 允许原始 2 类分类头被替换为 3 类
        base_model = AutoModelForSequenceClassification.from_pretrained(
            self.base_model_id,
            num_labels=len(SENTIMENT_LABELS),
            ignore_mismatched_sizes=True,
        )

        # 叠加 LoRA adapter
        model = PeftModel.from_pretrained(base_model, str(self.adapter_dir))
        model = model.merge_and_unload() if device == "cpu" else model
        model.eval()

        # 显式设置 3 分类标签映射（PEFT 合并后 id2label 可能被覆盖）
        model.config.id2label = {i: label for i, label in enumerate(SENTIMENT_LABELS)}
        model.config.label2id = {label: i for i, label in enumerate(SENTIMENT_LABELS)}

        # 加载 tokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(self.tokenizer_dir))

        # 创建 pipeline
        self._pipeline = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=0 if device == "cuda" else -1,
            batch_size=self.batch_size,
            top_k=None,
        )

        # 验证标签配置
        configured_labels = {_normalize_label(label) for label in model.config.id2label.values()}
        if configured_labels != set(SENTIMENT_LABELS):
            raise RuntimeError(
                "LoRA model is not a NEGATIVE/NEUTRAL/POSITIVE classifier: "
                f"{sorted(configured_labels)}"
            )

        adapter_sha = _read_adapter_sha(str(self.adapter_dir))
        self._model_version = f"{self.base_model_id}@lora-{adapter_sha[:8]}"
        logger.info("LoRA model loaded: %s", self._model_version)

    def predict(self, batch: list[str]) -> list[dict]:
        """批量推理，返回每条文本的 {label, score}。

        满足 ModelAdapter Protocol。
        """
        if self._pipeline is None:
            self.load()

        assert self._pipeline is not None

        results: list[dict] = []
        for text in batch:
            if not isinstance(text, str) or not text.strip():
                results.append({"label": "NEUTRAL", "score": 0.0})
                continue

            raw_output = self._pipeline(text.strip())
            scores = _parse_pipeline_scores(raw_output)

            # 复用 SentimentClassifier 的校准逻辑
            clf = _get_calibrate_fn()
            calibrated_label, top_score = clf(scores, text.strip())
            results.append({"label": calibrated_label, "score": top_score})

        return results

    def predict_single(self, text: str):
        """单条推理，返回 SentimentResult。

        与 SentimentClassifier.predict_single 接口对齐，
        便于 evaluate_sentiment.py 中复用评测逻辑。
        """
        from app.analytics.sentiment_classifier import SentimentResult

        if not isinstance(text, str) or not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.model_version,
            )

        if self._pipeline is None:
            self.load()

        assert self._pipeline is not None

        raw_output = self._pipeline(text.strip())
        scores = _parse_pipeline_scores(raw_output)
        clf = _get_calibrate_fn()
        calibrated_label, top_score = clf(scores, text.strip())

        return SentimentResult(
            sentiment=calibrated_label,
            confidence=top_score,
            model_version=self.model_version,
        )


class BaselineModelLoader:
    """加载基线模型（不带 LoRA adapter）并提供统一推理接口。

    基线 = 基础模型以 num_labels=3 加载（分类头随机初始化），
    与 LoRA 训练的起始状态完全一致，但不叠加 adapter。
    这代表了"LoRA 训练前"的模型性能。
    """

    def __init__(
        self,
        base_model_id: str,
        batch_size: int = 32,
    ):
        self.base_model_id = base_model_id
        self.batch_size = batch_size
        self._pipeline = None
        self._model_version: str | None = None

    @property
    def model_version(self) -> str:
        """返回模型版本标识。"""
        if self._model_version is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._model_version

    def load(self) -> None:
        """加载基线模型（num_labels=3，与训练时一致）但不叠加 adapter。"""
        import torch
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            pipeline,
        )

        device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            "Loading baseline model: %s, device=%s",
            self.base_model_id,
            device,
        )

        # 以 num_labels=3 加载（与训练时一致，分类头随机初始化）
        # ignore_mismatched_sizes=True 允许原始 2 类分类头被替换为 3 类
        model = AutoModelForSequenceClassification.from_pretrained(
            self.base_model_id,
            num_labels=len(SENTIMENT_LABELS),
            ignore_mismatched_sizes=True,
        )
        model.eval()

        # 显式设置 3 分类标签映射
        model.config.id2label = {i: label for i, label in enumerate(SENTIMENT_LABELS)}
        model.config.label2id = {label: i for i, label in enumerate(SENTIMENT_LABELS)}

        tokenizer = AutoTokenizer.from_pretrained(self.base_model_id)

        self._pipeline = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=0 if device == "cuda" else -1,
            batch_size=self.batch_size,
            top_k=None,
        )

        self._model_version = f"{self.base_model_id}@baseline"
        logger.info("Baseline model loaded: %s", self._model_version)

    def predict_single(self, text: str):
        """单条推理，返回 SentimentResult。"""
        from app.analytics.sentiment_classifier import SentimentResult

        if not isinstance(text, str) or not text.strip():
            return SentimentResult(
                sentiment="NEUTRAL",
                confidence=0.0,
                model_version=self.model_version,
            )

        if self._pipeline is None:
            self.load()

        assert self._pipeline is not None

        raw_output = self._pipeline(text.strip())
        scores = _parse_pipeline_scores(raw_output)
        clf = _get_calibrate_fn()
        calibrated_label, top_score = clf(scores, text.strip())

        return SentimentResult(
            sentiment=calibrated_label,
            confidence=top_score,
            model_version=self.model_version,
        )


# ── 辅助函数 ──────────────────────────────────────────────────


def _parse_pipeline_scores(raw_output) -> list[dict]:
    """从 pipeline 输出提取 {label, score} 列表。

    与 SentimentClassifier._parse_pipeline_scores 逻辑一致，
    但在模块顶层定义以避免访问私有方法。
    """
    if isinstance(raw_output, list) and len(raw_output) > 0:
        first = raw_output[0]
        if isinstance(first, list):
            return first
        if isinstance(first, dict):
            return raw_output
    return [{"label": "NEUTRAL", "score": 0.0}]


def _get_calibrate_fn():
    """获取 SentimentClassifier 的校准函数实例。

    创建一个临时的 SentimentClassifier 实例（不加载模型），
    复用其 _calibrate_neutral 方法确保后处理逻辑一致。
    """
    clf = SentimentClassifier()
    return clf._calibrate_neutral


def _read_adapter_sha(adapter_dir: str) -> str:
    """从 adapter 目录读取 SHA-256（从 training_snapshot.json）。

    如果无法读取则返回 unknown。
    """
    try:
        import json

        snapshot_path = Path(adapter_dir).parent / "config" / "training_snapshot.json"
        if snapshot_path.exists():
            with snapshot_path.open(encoding="utf-8") as f:
                snapshot = json.load(f)
                return snapshot.get("adapter_sha256", "unknown")
    except Exception:
        pass
    return "unknown"
