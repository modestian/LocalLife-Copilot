"""模型卡生成器。

具体设计 §9.3：保存 Adapter、Tokenizer、训练参数、依赖版本、Git commit、曲线和 Model Card。
ST-502 验收准则 ④：模型卡记录数据、配置、指标、限制和人工抽检结论。

从 training_snapshot.json、evaluation_report.json 和 human_review_samples.jsonl
组装结构化模型卡 JSON，供发布门禁检查和前端展示使用。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 模型卡必填字段（供 PublishingGate 校验）
REQUIRED_MODEL_CARD_FIELDS = (
    "model_name",
    "version",
    "task_type",
    "base_model_ref",
    "method",
    "adapter_sha256",
    "training",
    "metrics",
    "gate_result",
    "limitations",
    "human_review",
)


@dataclass(frozen=True, slots=True)
class ModelCardResult:
    """模型卡生成结果。"""

    card: dict[str, object]
    """模型卡字典。"""
    output_path: str
    """保存路径。"""


class ModelCardGenerator:
    """从训练快照和评测报告组装结构化模型卡。

    模型卡包含以下区块：
    - 模型元数据（名称、版本、任务类型、基模型、方法、adapter SHA-256）
    - 训练信息（超参数、Git commit、依赖版本、smoke 模式）
    - 数据集信息（hash、样本量、分切分布）
    - 评测指标（基线 vs LoRA 对比、各类别 P/R/F1、混淆矩阵）
    - 门禁结果（3 项门禁检查状态）
    - 已知限制（自动从误差分析提取）
    - 人工抽检摘要
    """

    def __init__(self, job_id: str, artifact_root: str | Path):
        self.job_id = job_id
        self.artifact_root = Path(artifact_root)

    def generate(
        self,
        eval_report: dict,
        *,
        training_snapshot: dict | None = None,
        human_review_samples: list[dict] | None = None,
    ) -> dict[str, object]:
        """生成模型卡字典。

        Args:
            eval_report: 评测报告字典（evaluate_model.py 输出）。
            training_snapshot: 训练快照字典。如为 None 则从
                artifacts/{job_id}/config/training_snapshot.json 读取。
            human_review_samples: 人工抽检样本列表。如为 None 则从
                reports/{job_id}/human_review_samples.jsonl 读取。

        Returns:
            结构化模型卡字典。
        """
        # 加载训练快照
        if training_snapshot is None:
            training_snapshot = self._load_training_snapshot()

        # 加载人工抽检样本
        if human_review_samples is None:
            human_review_samples = self._load_human_review_samples(eval_report)

        # 组装模型卡
        card = self._build_card(eval_report, training_snapshot, human_review_samples)
        logger.info("Model card generated for job %s", self.job_id)
        return card

    def generate_and_save(
        self,
        eval_report: dict,
        output_dir: str | Path,
        *,
        training_snapshot: dict | None = None,
        human_review_samples: list[dict] | None = None,
    ) -> ModelCardResult:
        """生成模型卡并保存为 JSON 文件。

        Args:
            eval_report: 评测报告字典。
            output_dir: 输出目录。
            training_snapshot: 训练快照（可选）。
            human_review_samples: 人工抽检样本（可选）。

        Returns:
            ModelCardResult 包含卡片字典和保存路径。
        """
        card = self.generate(
            eval_report,
            training_snapshot=training_snapshot,
            human_review_samples=human_review_samples,
        )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        card_path = output_dir / "model_card.json"
        with card_path.open("w", encoding="utf-8") as f:
            json.dump(card, f, indent=2, ensure_ascii=False)

        logger.info("Model card saved to %s", card_path)
        return ModelCardResult(card=card, output_path=str(card_path))

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_training_snapshot(self) -> dict:
        """从 artifacts/{job_id}/config/training_snapshot.json 加载训练快照。"""
        snapshot_path = self.artifact_root / "config" / "training_snapshot.json"
        if not snapshot_path.exists():
            logger.warning("Training snapshot not found: %s", snapshot_path)
            return {}
        with snapshot_path.open(encoding="utf-8") as f:
            return json.load(f)

    def _load_human_review_samples(self, eval_report: dict) -> list[dict]:
        """从 reports/{job_id}/human_review_samples.jsonl 加载抽检样本。

        如果文件不存在，返回空列表。
        """
        report_dir = Path(eval_report.get("_report_dir", ""))
        if not report_dir:
            # 尝试从默认路径加载
            report_dir = Path(__file__).resolve().parent / "reports" / self.job_id
        review_path = report_dir / "human_review_samples.jsonl"
        if not review_path.exists():
            logger.warning("Human review samples not found: %s", review_path)
            return []

        samples: list[dict] = []
        with review_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(json.loads(line))
        return samples

    def _build_card(
        self,
        eval_report: dict,
        snapshot: dict,
        review_samples: list[dict],
    ) -> dict[str, object]:
        """组装模型卡字典。"""
        training_config = snapshot.get("training_config", {})

        # 提取指标
        baseline = eval_report.get("baseline", {})
        lora = eval_report.get("lora", {})
        comparison = eval_report.get("comparison", {})
        gate = comparison.get("gate", {})

        # 提取误差分析摘要
        error_analysis = eval_report.get("error_analysis", {})
        error_summary = error_analysis.get("summary", {})

        # 自动生成 limitations
        limitations = self._generate_limitations(
            snapshot=snapshot,
            error_analysis=error_analysis,
            gate=gate,
        )

        # 人工抽检摘要
        human_review = self._build_human_review_summary(review_samples)

        # 数据集信息
        dataset_info = self._build_dataset_info(snapshot, eval_report)

        return {
            "model_name": "sentiment-roberta-lora",
            "version": self.job_id,
            "task_type": training_config.get("task_type", "sentiment_classification"),
            "base_model_ref": training_config.get(
                "base_model_id",
                lora.get("model", "unknown"),
            ),
            "method": training_config.get("method", "LORA"),
            "adapter_sha256": snapshot.get(
                "adapter_sha256",
                lora.get("adapter_sha256", "unknown"),
            ),
            "training": {
                "hyperparameters": training_config.get("hyperparameters", {}),
                "git_commit": snapshot.get("git_commit", "unknown"),
                "dependencies": snapshot.get("dependencies", {}),
                "smoke_mode": training_config.get("smoke_mode", False),
                "training_metrics": snapshot.get("metrics", {}),
            },
            "dataset": dataset_info,
            "metrics": {
                "baseline_macro_f1": baseline.get("macro_f1", 0.0),
                "lora_macro_f1": lora.get("macro_f1", 0.0),
                "macro_f1_delta": comparison.get("macro_f1_delta", 0.0),
                "baseline_negative_recall": baseline.get("negative_recall", 0.0),
                "lora_negative_recall": lora.get("negative_recall", 0.0),
                "negative_recall_delta": comparison.get("negative_recall_delta", 0.0),
                "baseline_accuracy": baseline.get("accuracy", 0.0),
                "lora_accuracy": lora.get("accuracy", 0.0),
                "per_class": lora.get("per_class", {}),
                "confusion_matrix": lora.get("confusion_matrix", {}),
                "calibration": lora.get("calibration", {}),
            },
            "gate_result": {
                "gate_passed": gate.get("gate_passed", False),
                "checks": gate.get("checks", []),
                "summary": gate.get("summary", {}),
            },
            "error_analysis_summary": error_summary,
            "limitations": limitations,
            "human_review": human_review,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _generate_limitations(
        self,
        *,
        snapshot: dict,
        error_analysis: dict,
        gate: dict,
    ) -> list[str]:
        """从训练快照、误差分析和门禁结果自动生成限制说明。"""
        limitations: list[str] = []

        # 1. 基线模型架构限制
        training_config = snapshot.get("training_config", {})
        base_model = training_config.get("base_model_id", "")
        if base_model:
            limitations.append(
                f"基线模型 {base_model} 原为 2 分类（NEGATIVE/POSITIVE），"
                "分类头随机初始化后需 LoRA 微调才能进行 3 分类"
            )

        # 2. LoRA 高置信度错分
        high_conf = error_analysis.get("high_confidence_errors", {})
        lora_high_conf = high_conf.get("lora", [])
        if lora_high_conf:
            limitations.append(
                f"LoRA 高置信度错分 {len(lora_high_conf)} 条（置信度 >= 0.8），需关注边界样本"
            )

        # 3. 退化样本
        error_summary = error_analysis.get("summary", {})
        regressions = error_summary.get("regressions", 0)
        if regressions > 0:
            limitations.append(
                f"LoRA 退化样本 {regressions} 条（基线正确但 LoRA 预测错误），需评估是否引入新偏差"
            )

        # 4. 门禁未通过项
        checks = gate.get("checks", [])
        failed_checks = [c for c in checks if not c.get("passed", False)]
        if failed_checks:
            failed_names = [c["name"] for c in failed_checks]
            limitations.append(f"评测门禁未通过项：{', '.join(failed_names)}，不可发布")

        # 5. smoke 模式
        if training_config.get("smoke_mode", False):
            limitations.append("模型在 smoke 模式下训练，仅用于验证流程，不可用于生产")

        return limitations

    def _build_dataset_info(
        self,
        snapshot: dict,
        eval_report: dict,
    ) -> dict[str, object]:
        """构建数据集信息区块。"""
        dataset_files = snapshot.get("dataset_files", {})
        training_config = snapshot.get("training_config", {})
        dataset_id = training_config.get("dataset_id", "unknown")

        # 从评测报告中提取测试集样本数
        test_sample_count = eval_report.get("baseline", {}).get("total", 0)

        return {
            "dataset_id": dataset_id,
            "dataset_files": dataset_files,
            "test_sample_count": test_sample_count,
        }

    def _build_human_review_summary(
        self,
        review_samples: list[dict],
    ) -> dict[str, object]:
        """构建人工抽检摘要。"""
        total = len(review_samples)
        reviewed = 0
        for sample in review_samples:
            scores = sample.get("scores", {})
            if scores.get("factual") is not None:
                reviewed += 1

        return {
            "total_samples": total,
            "reviewed": reviewed,
            "review_summary": (
                f"{reviewed}/{total} 条已完成人工抽检"
                if reviewed < total
                else "全部抽检样本已完成人工评审"
            ),
        }
