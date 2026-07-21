"""基线 / LoRA 同集评测核心脚本。

具体设计 §9.4：分类评测包含 Macro-F1、各类 Precision/Recall/F1、
混淆矩阵和置信度校准。

验收准则③：基线与 LoRA 使用同一测试集，关键负面召回不得下降，
总体指标不得低于基线，目标 Macro-F1 提升 ≥ 0.03。

用法::

    # 评测 LoRA 产物 lora-001（与基线对比）
    python -m evaluation.evaluate_model --job-id lora-001

    # 指定测试集
    python -m evaluation.evaluate_model --job-id lora-001 \\
        --test-file backend/training/data/test.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure Unicode output works on Windows GBK consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import UTC

from evaluation.error_analysis import (
    ErrorAnalyzer,
    generate_error_report,
)
from evaluation.human_review import HumanReviewGenerator

LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
LABEL_TO_IDX = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}

# 门禁阈值（验收准则③）
GATE_MIN_MACRO_F1_IMPROVEMENT = 0.03


def load_test_data(filepath: str) -> list[dict]:
    """加载测试集 JSONL，返回 [{text, label, ...}] 列表。"""
    data = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                # 训练数据用 label (int)，评测用 sentiment (str)
                if "label" in item and isinstance(item["label"], int):
                    item["sentiment"] = LABELS[item["label"]]
                data.append(item)
    return data


def evaluate_predictions(
    y_true: list[str],
    y_pred: list[str],
    confidences: list[float] | None = None,
) -> dict:
    """计算分类指标：per-class P/R/F1、Macro-F1、混淆矩阵、置信度校准。

    具体设计 §9.4：分类评测包含 Macro-F1、各类 Precision/Recall/F1、
    混淆矩阵和置信度校准。
    """
    # Per-class metrics
    per_class: dict[str, dict[str, float]] = {}
    for label in LABELS:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=False) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=False) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=False) if t == label and p != label)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }

    # Macro-F1
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(LABELS)
    macro_precision = sum(v["precision"] for v in per_class.values()) / len(LABELS)
    macro_recall = sum(v["recall"] for v in per_class.values()) / len(LABELS)

    # Confusion matrix (rows=true, cols=pred)
    confusion = {t: {p: 0 for p in LABELS} for t in LABELS}
    for t, p in zip(y_true, y_pred, strict=False):
        confusion[t][p] += 1

    # Accuracy
    correct = sum(1 for t, p in zip(y_true, y_pred, strict=False) if t == p)
    accuracy = correct / len(y_true) if y_true else 0.0

    # 置信度校准：按置信度分桶，统计每个桶的实际准确率
    calibration = None
    if confidences:
        calibration = _compute_calibration(y_true, y_pred, confidences)

    # Misclassified samples
    misclassified = []
    for i, (t, p) in enumerate(zip(y_true, y_pred, strict=False)):
        if t != p:
            misclassified.append(
                {
                    "index": i,
                    "true": t,
                    "pred": p,
                    "confidence": confidences[i] if confidences else None,
                }
            )

    return {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "calibration": calibration,
        "misclassified": misclassified,
        "total": len(y_true),
        "correct": correct,
        "negative_recall": per_class["NEGATIVE"]["recall"],
    }


def _compute_calibration(
    y_true: list[str],
    y_pred: list[str],
    confidences: list[float],
) -> dict:
    """置信度校准：按置信度分桶统计实际准确率。

    具体设计 §9.4：分类评测包含置信度校准。
    """
    bins = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    result = {}
    for low, high in bins:
        bucket_key = f"{low:.1f}-{high:.1f}"
        indices = [i for i, c in enumerate(confidences) if low <= c < high]
        if not indices:
            result[bucket_key] = {"count": 0, "avg_confidence": 0.0, "accuracy": 0.0}
            continue
        bucket_correct = sum(1 for i in indices if y_true[i] == y_pred[i])
        avg_conf = sum(confidences[i] for i in indices) / len(indices)
        result[bucket_key] = {
            "count": len(indices),
            "avg_confidence": round(avg_conf, 4),
            "accuracy": round(bucket_correct / len(indices), 4),
        }
    return result


def check_gates(baseline: dict, lora: dict) -> dict:
    """门禁检查（验收准则③）。

    - 关键负面召回不得下降
    - 总体指标不得低于基线（Macro-F1）
    - 目标 Macro-F1 提升 ≥ 0.03
    """
    checks = []

    # 1. 关键负面召回不得下降
    neg_recall_delta = lora["negative_recall"] - baseline["negative_recall"]
    neg_check = neg_recall_delta >= 0
    checks.append(
        {
            "name": "negative_recall_not_decreased",
            "description": "关键负面召回不得下降",
            "baseline_value": baseline["negative_recall"],
            "lora_value": lora["negative_recall"],
            "delta": round(neg_recall_delta, 4),
            "passed": neg_check,
        }
    )

    # 2. 总体 Macro-F1 不低于基线
    f1_delta = lora["macro_f1"] - baseline["macro_f1"]
    f1_not_below = f1_delta >= 0
    checks.append(
        {
            "name": "macro_f1_not_below_baseline",
            "description": "总体 Macro-F1 不得低于基线",
            "baseline_value": baseline["macro_f1"],
            "lora_value": lora["macro_f1"],
            "delta": round(f1_delta, 4),
            "passed": f1_not_below,
        }
    )

    # 3. 目标 Macro-F1 提升 ≥ 0.03
    f1_target_met = f1_delta >= GATE_MIN_MACRO_F1_IMPROVEMENT
    checks.append(
        {
            "name": "macro_f1_improvement_ge_0.03",
            "description": f"目标 Macro-F1 提升 ≥ {GATE_MIN_MACRO_F1_IMPROVEMENT}",
            "baseline_value": baseline["macro_f1"],
            "lora_value": lora["macro_f1"],
            "delta": round(f1_delta, 4),
            "threshold": GATE_MIN_MACRO_F1_IMPROVEMENT,
            "passed": f1_target_met,
        }
    )

    all_passed = all(c["passed"] for c in checks)

    return {
        "gate_passed": all_passed,
        "checks": checks,
        "summary": {
            "macro_f1_delta": round(f1_delta, 4),
            "negative_recall_delta": round(neg_recall_delta, 4),
            "all_passed": all_passed,
        },
    }


def evaluate_model_on_testset(
    test_data: list[dict],
    classifier,
) -> dict:
    """用给定分类器在测试集上评测，返回指标字典。

    Args:
        test_data: load_test_data 返回的列表。
        classifier: 具有 predict_single(text) -> SentimentResult 的对象。
    """
    y_true: list[str] = []
    y_pred: list[str] = []
    confidences: list[float] = []

    for sample in test_data:
        if "sentiment" in sample:
            true_label = sample["sentiment"]
        elif "label" in sample:
            true_label = LABELS[sample["label"]]
        else:
            true_label = "NEUTRAL"
        text_key = "text" if "text" in sample else "content"
        result = classifier.predict_single(sample[text_key])
        y_true.append(true_label)
        y_pred.append(result.sentiment)
        confidences.append(result.confidence)

    return evaluate_predictions(y_true, y_pred, confidences)


def save_report(
    report: dict,
    job_id: str,
    output_dir: str | Path | None = None,
) -> Path:
    """保存评测报告到 JSON 和 Markdown 文件。

    具体设计 §9.3：保存训练参数、依赖版本、曲线和 Model Card。
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "reports" / job_id
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON 报告
    json_path = output_dir / "evaluation_report.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Markdown 报告
    md_path = output_dir / "evaluation_report.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write(_generate_markdown_report(report))

    return json_path


def _generate_markdown_report(report: dict) -> str:
    """生成人类可读的 Markdown 评测报告。"""
    lines = [
        "# 同集评测报告",
        "",
        f"**任务 ID**: {report.get('job_id', 'N/A')}",
        f"**测试集**: {report.get('test_set', 'N/A')}",
        f"**评测时间**: {report.get('evaluated_at', 'N/A')}",
        "",
    ]

    baseline = report.get("baseline", {})
    lora = report.get("lora", {})
    summary = report.get("comparison", {}).get("summary", {})

    # 指标对比表
    lines.extend(
        [
            "## 指标对比",
            "",
            "| 指标 | 基线 | LoRA | 变化 |",
            "| --- | --- | --- | --- |",
            f"| Macro-F1 | {baseline.get('macro_f1', 'N/A')} | "
            f"{lora.get('macro_f1', 'N/A')} | "
            f"{summary.get('macro_f1_delta', 0):+.4f} |",
            f"| Accuracy | {baseline.get('accuracy', 'N/A')} | "
            f"{lora.get('accuracy', 'N/A')} | "
            f"{lora.get('accuracy', 0) - baseline.get('accuracy', 0):+.4f} |",
            f"| NEGATIVE Recall | {baseline.get('negative_recall', 'N/A')} | "
            f"{lora.get('negative_recall', 'N/A')} | "
            f"{summary.get('negative_recall_delta', 0):+.4f} |",
            "",
        ]
    )

    # 各类别指标
    for label in LABELS:
        b_cls = baseline.get("per_class", {}).get(label, {})
        l_cls = lora.get("per_class", {}).get(label, {})
        lines.extend(
            [
                f"### {label}",
                f"- 基线: P={b_cls.get('precision', 'N/A')} "
                f"R={b_cls.get('recall', 'N/A')} F1={b_cls.get('f1', 'N/A')}",
                f"- LoRA: P={l_cls.get('precision', 'N/A')} "
                f"R={l_cls.get('recall', 'N/A')} F1={l_cls.get('f1', 'N/A')}",
                "",
            ]
        )

    # 门禁结果
    gate = report.get("comparison", {}).get("gate", {})
    lines.extend(
        [
            "## 门禁结果",
            "",
            f"**通过**: {'✅' if gate.get('gate_passed') else '❌'}",
            "",
            "| 检查项 | 基线值 | LoRA值 | 变化 | 通过 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for check in gate.get("checks", []):
        passed_str = "✅" if check["passed"] else "❌"
        delta_str = f"{check.get('delta', 0):+.4f}" if "delta" in check else "N/A"
        lines.append(
            f"| {check['name']} | {check.get('baseline_value', 'N/A')} | "
            f"{check.get('lora_value', 'N/A')} | {delta_str} | {passed_str} |"
        )
    lines.append("")

    # 误差分析
    error_report = report.get("error_analysis_report", "")
    if error_report:
        lines.extend(["## 误差分析", "", error_report, ""])

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="基线 / LoRA 同集评测")
    parser.add_argument("--job-id", required=True, help="训练任务 ID（如 lora-001）")
    parser.add_argument(
        "--test-file",
        default="backend/training/data/test.jsonl",
        help="固定测试集路径",
    )
    parser.add_argument(
        "--base-model",
        default="uer/roberta-base-finetuned-dianping-chinese",
        help="基线模型 ID",
    )
    parser.add_argument(
        "--adapter-dir",
        default=None,
        help="Adapter 目录（默认从 artifacts/{job_id}/adapter 读取）",
    )
    parser.add_argument(
        "--tokenizer-dir",
        default=None,
        help="Tokenizer 目录（默认从 artifacts/{job_id}/tokenizer 读取）",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="报告输出目录（默认 evaluation/reports/{job_id}）",
    )
    parser.add_argument(
        "--skip-human-review",
        action="store_true",
        help="跳过人工抽检门禁（CI 环境使用）",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("基线 / LoRA 同集评测")
    print("=" * 60)

    # 加载测试集
    print(f"\n1. 加载测试集: {args.test_file}")
    test_data = load_test_data(args.test_file)
    print(f"   {len(test_data)} 条样本")

    # 确定产物路径
    artifact_root = Path("backend/training/artifacts") / args.job_id
    adapter_dir = Path(args.adapter_dir) if args.adapter_dir else artifact_root / "adapter"
    tokenizer_dir = Path(args.tokenizer_dir) if args.tokenizer_dir else artifact_root / "tokenizer"
    snapshot_path = artifact_root / "config" / "training_snapshot.json"

    # 2. 评测基线（base model 以 num_labels=3 加载，不叠加 adapter）
    print("\n2. 评测基线模型...")
    from evaluation.adapter_loader import BaselineModelLoader

    baseline_clf = BaselineModelLoader(base_model_id=args.base_model)
    baseline_clf.load()
    baseline_result = evaluate_model_on_testset(test_data, baseline_clf)
    print(f"   基线 Macro-F1: {baseline_result['macro_f1']}")
    print(f"   基线 NEGATIVE Recall: {baseline_result['negative_recall']}")

    # 3. 评测 LoRA
    print("\n3. 评测 LoRA 模型...")
    from evaluation.adapter_loader import LoRAAdapterLoader

    lora_loader = LoRAAdapterLoader(
        base_model_id=args.base_model,
        adapter_dir=adapter_dir,
        tokenizer_dir=tokenizer_dir,
    )
    lora_loader.load()
    lora_result = evaluate_model_on_testset(test_data, lora_loader)
    print(f"   LoRA Macro-F1: {lora_result['macro_f1']}")
    print(f"   LoRA NEGATIVE Recall: {lora_result['negative_recall']}")

    # 4. 门禁检查
    print("\n4. 门禁检查...")
    gate = check_gates(baseline_result, lora_result)
    for check in gate["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"   [{status}] {check['name']}: delta={check.get('delta', 'N/A')}")
    print(f"   门禁结果: {'通过' if gate['gate_passed'] else '未通过'}")

    # 5. 误差分析
    print("\n5. 误差分析...")
    analyzer = ErrorAnalyzer(
        test_data=test_data,
        baseline_result=baseline_result,
        lora_result=lora_result,
    )
    error_analysis = analyzer.analyze()
    error_report = generate_error_report(error_analysis, baseline_result, lora_result)
    print(error_report)

    # 6. 人工抽检样本生成
    print("\n6. 生成人工抽检样本...")
    review_gen = HumanReviewGenerator(
        test_data=test_data,
        baseline_result=baseline_result,
        lora_result=lora_result,
    )
    review_samples = review_gen.generate()

    # 7. 保存报告
    print("\n7. 保存报告...")
    from datetime import datetime

    # 读取训练快照中的 adapter_sha256
    adapter_sha256 = "unknown"
    if snapshot_path.exists():
        with snapshot_path.open(encoding="utf-8") as f:
            snapshot = json.load(f)
            adapter_sha256 = snapshot.get("adapter_sha256", "unknown")

    report = {
        "job_id": args.job_id,
        "test_set": args.test_file,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "baseline": {
            "model": args.base_model,
            **{k: v for k, v in baseline_result.items() if k != "misclassified"},
        },
        "lora": {
            "model": args.base_model,
            "adapter_sha256": adapter_sha256,
            **{k: v for k, v in lora_result.items() if k != "misclassified"},
        },
        "comparison": {
            "macro_f1_delta": round(lora_result["macro_f1"] - baseline_result["macro_f1"], 4),
            "negative_recall_delta": round(
                lora_result["negative_recall"] - baseline_result["negative_recall"], 4
            ),
            "gate": gate,
            "summary": gate["summary"],
        },
        "error_analysis": error_analysis,
        "error_analysis_report": error_report,
    }

    output_dir = Path(args.output_dir) if args.output_dir else None
    json_path = save_report(report, args.job_id, output_dir)
    print(f"   报告保存到: {json_path}")

    # 保存人工抽检样本
    review_path = json_path.parent / "human_review_samples.jsonl"
    with review_path.open("w", encoding="utf-8") as f:
        for sample in review_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    print(f"   抽检样本保存到: {review_path} ({len(review_samples)} 条)")

    # 8. 生成模型卡
    print("\n8. 生成模型卡...")
    from evaluation.model_card import ModelCardGenerator

    # 加载完整训练快照
    training_snapshot = {}
    if snapshot_path.exists():
        with snapshot_path.open(encoding="utf-8") as f:
            training_snapshot = json.load(f)

    card_gen = ModelCardGenerator(
        job_id=args.job_id,
        artifact_root=artifact_root,
    )
    card_result = card_gen.generate_and_save(
        eval_report=report,
        output_dir=json_path.parent,
        training_snapshot=training_snapshot,
        human_review_samples=review_samples,
    )
    print(f"   模型卡保存到: {card_result.output_path}")

    # 9. 发布门禁检查
    print("\n9. 发布门禁检查...")
    from evaluation.publishing_gate import PublishingGate

    gate_checker = PublishingGate()
    gate_result = gate_checker.check_and_save(
        model_card=card_result.card,
        eval_report=report,
        human_reviews=review_samples,
        output_dir=json_path.parent,
        training_snapshot=training_snapshot,
        skip_human_review=args.skip_human_review,
    )
    for check in gate_result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"   [{status}] {check.name}: {check.reason}")
    print(f"   门禁决策: {gate_result.decision}")

    print("\n" + "=" * 60)
    print("评测完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
