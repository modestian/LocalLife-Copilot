"""人工抽检样本生成模块。

具体设计 §9.4：人工从事实性、针对性、礼貌性、安全性评分，
并检查禁用承诺。

生成策略：
1. 全部错分样本（基线或 LoRA 中至少一个预测错误）
2. 全部退化样本（基线对→LoRA错）
3. 边界样本（confidence 在 0.5-0.7 之间的预测）
4. 随机抽取正确样本（确保覆盖三个类别）
"""

from __future__ import annotations

import json
import random

LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]

# 默认随机种子，与训练保持一致
DEFAULT_SEED = 42

# 抽检每类正确样本数量
CORRECT_SAMPLES_PER_CLASS = 5

# 边界样本置信度范围
BOUNDARY_CONFIDENCE_LOW = 0.5
BOUNDARY_CONFIDENCE_HIGH = 0.7


class HumanReviewGenerator:
    """生成人工抽检样本集。

    抽检样本包含：
    - 全部错分样本（至少一个模型预测错误）
    - 边界样本（置信度在 0.5-0.7 之间）
    - 每类随机抽取的正确样本

    每个样本附带评分模板（事实性、针对性、礼貌性、安全性、禁用承诺检查）。
    """

    def __init__(
        self,
        test_data: list[dict],
        baseline_result: dict,
        lora_result: dict,
        seed: int = DEFAULT_SEED,
    ):
        self.test_data = test_data
        self.baseline_result = baseline_result
        self.lora_result = lora_result
        self.rng = random.Random(seed)

    def generate(self) -> list[dict]:
        """生成人工抽检样本列表。"""
        # 收集所有错分样本索引
        baseline_mis_indices = {m["index"] for m in self.baseline_result["misclassified"]}
        lora_mis_indices = {m["index"] for m in self.lora_result["misclassified"]}
        error_indices = baseline_mis_indices | lora_mis_indices

        # 收集边界样本索引
        boundary_indices = set()
        for m in self.baseline_result.get("misclassified", []):
            conf = m.get("confidence")
            if conf is not None and BOUNDARY_CONFIDENCE_LOW <= conf <= BOUNDARY_CONFIDENCE_HIGH:
                boundary_indices.add(m["index"])
        for m in self.lora_result.get("misclassified", []):
            conf = m.get("confidence")
            if conf is not None and BOUNDARY_CONFIDENCE_LOW <= conf <= BOUNDARY_CONFIDENCE_HIGH:
                boundary_indices.add(m["index"])

        # 合并错分 + 边界
        review_indices = set(error_indices) | set(boundary_indices)

        # 每类随机抽取正确样本
        correct_by_class: dict[str, list[int]] = {label: [] for label in LABELS}
        for i, sample in enumerate(self.test_data):
            if i in review_indices:
                continue
            true_label = sample.get(
                "sentiment",
                LABELS[sample["label"]] if "label" in sample else "NEUTRAL",
            )
            # 两个模型都预测正确
            if i not in baseline_mis_indices and i not in lora_mis_indices:
                correct_by_class[true_label].append(i)

        for _label, indices in correct_by_class.items():
            self.rng.shuffle(indices)
            review_indices.update(indices[:CORRECT_SAMPLES_PER_CLASS])

        # 按索引排序生成最终列表
        samples = []
        for idx in sorted(review_indices):
            sample = self.test_data[idx]
            text = sample.get("text", sample.get("content", ""))
            true_label = sample.get(
                "sentiment",
                LABELS[sample["label"]] if "label" in sample else "NEUTRAL",
            )

            # 获取两个模型的预测
            b_mis = next(
                (m for m in self.baseline_result["misclassified"] if m["index"] == idx), None
            )
            l_mis = next((m for m in self.lora_result["misclassified"] if m["index"] == idx), None)

            b_pred = b_mis["pred"] if b_mis else true_label
            l_pred = l_mis["pred"] if l_mis else true_label
            b_conf = b_mis["confidence"] if b_mis else None
            l_conf = l_mis["confidence"] if l_mis else None

            # 确定样本类型
            b_wrong = b_mis is not None
            l_wrong = l_mis is not None
            if b_wrong and not l_wrong:
                sample_type = "improvement"
            elif not b_wrong and l_wrong:
                sample_type = "regression"
            elif b_wrong and l_wrong:
                sample_type = "both_wrong"
            else:
                sample_type = "correct"

            entry = {
                "sample_id": idx,
                "text": text,
                "true_label": true_label,
                "baseline_pred": b_pred,
                "lora_pred": l_pred,
                "baseline_confidence": b_conf,
                "lora_confidence": l_conf,
                "sample_type": sample_type,
                "review_criteria": {
                    "factual_accuracy": None,  # 事实性评分 1-5
                    "relevance": None,  # 针对性评分 1-5
                    "politeness": None,  # 礼貌性评分 1-5
                    "safety": None,  # 安全性评分 1-5
                    "banned_commitment_check": None,  # 是否涉及禁用承诺
                    "reviewer_notes": "",  # 人工备注
                },
            }
            samples.append(entry)

        return samples

    def save(self, samples: list[dict], output_path: str) -> None:
        """保存抽检样本到 JSONL 文件。"""
        with open(output_path, "w", encoding="utf-8") as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
