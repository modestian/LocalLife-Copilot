"""误差分析模块：对比基线和 LoRA 的错分模式。

具体设计 §9.4：分类评测包含 Macro-F1、各类 Precision/Recall/F1、
混淆矩阵和置信度校准。

本模块提供：
- 逐样本对比：改善（基线错→LoRA对）、退化（基线对→LoRA错）、一致
- 错分方向统计
- 高置信度错分识别
- 置信度校准分析
- 边界样本识别（两个模型预测不一致）
"""

from __future__ import annotations

from collections import Counter

LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]


class ErrorAnalyzer:
    """对比基线和 LoRA 在同一测试集上的预测差异。

    Args:
        test_data: 测试集样本列表（含 text 和 true label）。
        baseline_result: evaluate_predictions 返回的基线指标。
        lora_result: evaluate_predictions 返回的 LoRA 指标。
    """

    def __init__(
        self,
        test_data: list[dict],
        baseline_result: dict,
        lora_result: dict,
    ):
        self.test_data = test_data
        self.baseline_result = baseline_result
        self.lora_result = lora_result

    def analyze(self) -> dict:
        """执行完整误差分析，返回结构化结果。"""
        baseline_mis = {m["index"]: m for m in self.baseline_result["misclassified"]}
        lora_mis = {m["index"]: m for m in self.lora_result["misclassified"]}

        improvements = []
        regressions = []
        disagreements = []

        all_indices = set(baseline_mis.keys()) | set(lora_mis.keys())
        for idx in sorted(all_indices):
            b_wrong = idx in baseline_mis
            l_wrong = idx in lora_mis

            sample = self.test_data[idx]
            text = sample.get("text", sample.get("content", ""))
            true_label = sample.get(
                "sentiment",
                LABELS[sample["label"]] if "label" in sample else "NEUTRAL",
            )

            b_pred = baseline_mis.get(idx, {}).get("pred", true_label)
            l_pred = lora_mis.get(idx, {}).get("pred", true_label)
            b_conf = baseline_mis.get(idx, {}).get("confidence")
            l_conf = lora_mis.get(idx, {}).get("confidence")

            entry = {
                "index": idx,
                "text": text[:100],
                "true": true_label,
                "baseline_pred": b_pred,
                "lora_pred": l_pred,
                "baseline_confidence": b_conf,
                "lora_confidence": l_conf,
            }

            if b_wrong and not l_wrong:
                improvements.append(entry)
            elif not b_wrong and l_wrong:
                regressions.append(entry)
            elif b_wrong and l_wrong and b_pred != l_pred:
                disagreements.append(entry)
            elif b_wrong and l_wrong and b_pred == l_pred:
                # 两个模型都错了且方向相同，归入共同错误
                pass
            elif not b_wrong and not l_wrong and b_pred != l_pred:
                # 不可能：两个都正确但预测不同（正确=预测=真实）
                pass

        # 错分方向统计
        baseline_directions = self._count_error_directions(baseline_mis)
        lora_directions = self._count_error_directions(lora_mis)

        # 高置信度错分
        high_conf_baseline = [
            m
            for m in self.baseline_result["misclassified"]
            if m.get("confidence") is not None and m["confidence"] >= 0.8
        ]
        high_conf_lora = [
            m
            for m in self.lora_result["misclassified"]
            if m.get("confidence") is not None and m["confidence"] >= 0.8
        ]

        return {
            "improvements": improvements,
            "regressions": regressions,
            "disagreements": disagreements,
            "error_direction_stats": {
                "baseline": dict(baseline_directions),
                "lora": dict(lora_directions),
            },
            "high_confidence_errors": {
                "baseline": high_conf_baseline,
                "lora": high_conf_lora,
            },
            "summary": {
                "total_test_samples": len(self.test_data),
                "baseline_errors": len(self.baseline_result["misclassified"]),
                "lora_errors": len(self.lora_result["misclassified"]),
                "improvements": len(improvements),
                "regressions": len(regressions),
                "disagreements": len(disagreements),
                "net_improvement": len(improvements) - len(regressions),
            },
        }

    def _count_error_directions(self, misclassified: dict) -> Counter:
        """统计错分方向（如 NEGATIVE→POSITIVE）。"""
        directions: Counter = Counter()
        for m in misclassified.values():
            key = f"{m['true']}→{m['pred']}"
            directions[key] += 1
        return directions


def generate_error_report(
    error_analysis: dict,
    baseline_result: dict,
    lora_result: dict,
) -> str:
    """生成人类可读的误差分析报告。"""
    lines: list[str] = []
    summary = error_analysis["summary"]

    lines.append(f"   总测试样本: {summary['total_test_samples']}")
    lines.append(f"   基线错分数: {summary['baseline_errors']}")
    lines.append(f"   LoRA 错分数: {summary['lora_errors']}")
    lines.append(f"   改善样本（基线错→LoRA对）: {summary['improvements']}")
    lines.append(f"   退化样本（基线对→LoRA错）: {summary['regressions']}")
    lines.append(f"   预测不一致（两模型预测不同）: {summary['disagreements']}")
    lines.append(f"   净改善: {summary['net_improvement']}")

    # 错分方向
    lines.append("\n   错分方向统计:")
    lines.append("     基线:")
    for direction, count in sorted(
        error_analysis["error_direction_stats"]["baseline"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"       {direction}: {count}")
    lines.append("     LoRA:")
    for direction, count in sorted(
        error_analysis["error_direction_stats"]["lora"].items(), key=lambda x: -x[1]
    ):
        lines.append(f"       {direction}: {count}")

    # 高置信度错分
    high_conf = error_analysis["high_confidence_errors"]
    lines.append("\n   高置信度错分（≥0.8）:")
    lines.append(f"     基线: {len(high_conf['baseline'])} 条")
    lines.append(f"     LoRA: {len(high_conf['lora'])} 条")

    # 退化样本详情
    regressions = error_analysis["regressions"]
    if regressions:
        lines.append(f"\n   退化样本详情（{len(regressions)} 条）:")
        for item in regressions[:10]:
            lines.append(
                f"     [{item['true']}→{item['lora_pred']} "
                f"conf={item.get('lora_confidence', 'N/A')}] "
                f"{item['text'][:60]}..."
            )

    # 改善样本详情
    improvements = error_analysis["improvements"]
    if improvements:
        lines.append(f"\n   改善样本详情（{len(improvements)} 条）:")
        for item in improvements[:10]:
            lines.append(
                f"     [{item['true']} 基线→{item['baseline_pred']} LoRA→正确] "
                f"{item['text'][:60]}..."
            )

    return "\n".join(lines)
