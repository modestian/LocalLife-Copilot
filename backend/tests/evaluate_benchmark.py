import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics import AspectExtractor
from app.analytics.sentiment_classifier import SentimentClassifier

LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]


def load_benchmark(filepath: str) -> list[dict]:
    """Load JSONL benchmark data, normalizing field names across formats.

    Supported formats:
      - benchmark_reviews.jsonl:  content / negative_reason
      - training_data_1000.jsonl: text   / negative_reasons
    After loading, every sample uses: content / aspect_labels / negative_reason / sentiment.
    """
    data = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                sample = json.loads(line)
                # Normalize text field
                if "text" in sample and "content" not in sample:
                    sample["content"] = sample.pop("text")
                # Normalize negative reason field
                if "negative_reasons" in sample and "negative_reason" not in sample:
                    sample["negative_reason"] = sample.pop("negative_reasons")
                data.append(sample)
    return data


def evaluate_aspect_extraction(benchmark_data: list[dict]) -> dict:
    tp_aspect = 0
    fp_aspect = 0
    fn_aspect = 0
    total_aspect_labels = 0
    predicted_aspect_labels = 0

    for sample in benchmark_data:
        text = sample["content"]
        expected_aspects = set(sample["aspect_labels"])
        predicted_aspects = set(AspectExtractor.extract_aspects(text))

        total_aspect_labels += len(expected_aspects)
        predicted_aspect_labels += len(predicted_aspects)

        for aspect in expected_aspects:
            if aspect in predicted_aspects:
                tp_aspect += 1
            else:
                fn_aspect += 1

        for aspect in predicted_aspects:
            if aspect not in expected_aspects:
                fp_aspect += 1

    precision = tp_aspect / (tp_aspect + fp_aspect) if (tp_aspect + fp_aspect) > 0 else 0.0
    recall = tp_aspect / (tp_aspect + fn_aspect) if (tp_aspect + fn_aspect) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp_aspect,
        "fp": fp_aspect,
        "fn": fn_aspect,
        "total_expected": total_aspect_labels,
        "total_predicted": predicted_aspect_labels,
    }


def evaluate_negative_reasons(benchmark_data: list[dict]) -> dict:
    negative_samples = [s for s in benchmark_data if s["sentiment"] == "NEGATIVE"]
    total_samples = len(negative_samples)
    tp_reason = 0
    fp_reason = 0
    fn_reason = 0
    total_reason_labels = 0
    predicted_reason_labels = 0

    for sample in negative_samples:
        text = sample["content"]
        expected_reasons = set(sample["negative_reason"])
        predicted_reasons = set(AspectExtractor.extract_negative_reasons(text))

        total_reason_labels += len(expected_reasons)
        predicted_reason_labels += len(predicted_reasons)

        for reason in expected_reasons:
            if reason in predicted_reasons:
                tp_reason += 1
            else:
                fn_reason += 1

        for reason in predicted_reasons:
            if reason not in expected_reasons:
                fp_reason += 1

    precision = tp_reason / (tp_reason + fp_reason) if (tp_reason + fp_reason) > 0 else 0.0
    recall = tp_reason / (tp_reason + fn_reason) if (tp_reason + fn_reason) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp_reason,
        "fp": fp_reason,
        "fn": fn_reason,
        "total_expected": total_reason_labels,
        "total_predicted": predicted_reason_labels,
        "negative_samples": total_samples,
    }


def analyze_sentiment_distribution(benchmark_data: list[dict]) -> dict:
    distribution = Counter(s["sentiment"] for s in benchmark_data)
    return dict(distribution)


def evaluate_sentiment_classification(
    benchmark_data: list[dict],
    classifier: SentimentClassifier | None = None,
) -> dict | None:
    """Evaluate three-class sentiment classification.

    Returns per-class P/R/F1, Macro-F1, and a 3×3 confusion matrix.
    If *classifier* is None the function tries to instantiate one;
    if model loading fails it returns None so the caller can skip gracefully.
    """
    if classifier is None:
        try:
            classifier = SentimentClassifier()
            classifier.load_model()
        except Exception as exc:
            print(f"   ⚠ 模型加载失败，跳过情感分类评测: {exc}")
            return None

    # Collect predictions
    y_true: list[str] = []
    y_pred: list[str] = []
    misclassified: list[dict] = []

    for sample in benchmark_data:
        true_label = sample["sentiment"]
        result = classifier.predict_single(sample["content"])
        pred_label = result.sentiment
        y_true.append(true_label)
        y_pred.append(pred_label)
        if true_label != pred_label:
            misclassified.append(
                {
                    "content": sample["content"][:60],
                    "true": true_label,
                    "pred": pred_label,
                    "confidence": result.confidence,
                }
            )

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
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": tp + fn,
        }

    # Macro-F1
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(LABELS)

    # Confusion matrix (rows=true, cols=pred)
    confusion = {t: {p: 0 for p in LABELS} for t in LABELS}
    for t, p in zip(y_true, y_pred, strict=False):
        confusion[t][p] += 1

    return {
        "per_class": per_class,
        "macro_f1": macro_f1,
        "confusion_matrix": confusion,
        "misclassified": misclassified,
        "total": len(y_true),
        "correct": sum(1 for t, p in zip(y_true, y_pred, strict=False) if t == p),
    }


def generate_error_report(sentiment_result: dict | None) -> str:
    """Generate a human-readable error analysis report."""
    if sentiment_result is None:
        return "   （情感分类评测未执行，无法生成误差报告）"

    lines: list[str] = []
    total = sentiment_result["total"]
    correct = sentiment_result["correct"]
    accuracy = correct / total if total > 0 else 0.0
    errors = total - correct

    lines.append(f"   准确率: {accuracy:.4f}  ({correct}/{total})")
    lines.append(f"   错分样本数: {errors}")

    # Error pattern statistics
    error_patterns: dict[str, int] = Counter()
    for item in sentiment_result["misclassified"]:
        key = f"{item['true']} → {item['pred']}"
        error_patterns[key] += 1

    if error_patterns:
        lines.append("   错分方向统计:")
        for pattern, count in sorted(error_patterns.items(), key=lambda x: -x[1]):
            lines.append(f"     {pattern}: {count} 条")

    # High-confidence misclassifications
    high_conf_errors = [m for m in sentiment_result["misclassified"] if m["confidence"] >= 0.8]
    if high_conf_errors:
        lines.append(f"   高置信度错分（≥0.8）: {len(high_conf_errors)} 条")
        for item in high_conf_errors[:5]:
            lines.append(
                f"     [{item['true']}→{item['pred']} conf={item['confidence']:.2f}] "
                f"{item['content']}..."
            )

    return "\n".join(lines)


def main():
    # Support command-line argument: python evaluate_benchmark.py [path]
    if len(sys.argv) > 1:
        benchmark_path = sys.argv[1]
    else:
        benchmark_path = "tests/data/training_data_1000.jsonl"

    print("=" * 60)
    print("大众点评AI智能助手 - 基准样本离线评测")
    print("=" * 60)

    print("\n1. 加载基准数据...")
    benchmark_data = load_benchmark(benchmark_path)
    print(f"   成功加载 {len(benchmark_data)} 条样本")

    print("\n2. 情感分布统计:")
    distribution = analyze_sentiment_distribution(benchmark_data)
    for sentiment, count in distribution.items():
        percentage = count / len(benchmark_data) * 100
        print(f"   {sentiment}: {count} 条 ({percentage:.1f}%)")

    # ── 3. 三分类情感评测（Macro-F1 + 混淆矩阵）──
    print("\n3. 三分类情感评测:")
    sentiment_result = evaluate_sentiment_classification(benchmark_data)
    if sentiment_result is not None:
        print(f"   整体准确率: {sentiment_result['correct']}/{sentiment_result['total']}")
        print(f"   Macro-F1:   {sentiment_result['macro_f1']:.4f}")
        print("   各类别指标:")
        for label, metrics in sentiment_result["per_class"].items():
            print(
                f"     {label:10s}  P={metrics['precision']:.4f}  "
                f"R={metrics['recall']:.4f}  F1={metrics['f1']:.4f}  "
                f"support={metrics['support']}"
            )
        # Confusion matrix
        cm = sentiment_result["confusion_matrix"]
        print("   混淆矩阵 (行=真实, 列=预测):")
        header = "            " + "  ".join(f"{label:>10s}" for label in LABELS)
        print(f"   {header}")
        for true_label in LABELS:
            row = "  ".join(f"{cm[true_label][pred]:>10d}" for pred in LABELS)
            print(f"   {true_label:10s}{row}")
    else:
        print("   ⚠ 跳过（模型未就绪）")

    # ── 4. 方面词提取评测 ──
    print("\n4. 方面词提取评测:")
    aspect_result = evaluate_aspect_extraction(benchmark_data)
    print(f"   精确率(Precision): {aspect_result['precision']:.4f}")
    print(f"   召回率(Recall):    {aspect_result['recall']:.4f}")
    print(f"   F1值(F1-Score):    {aspect_result['f1']:.4f}")
    print(f"   统计: TP={aspect_result['tp']}, FP={aspect_result['fp']}, FN={aspect_result['fn']}")
    print(
        f"   标签: 期望{aspect_result['total_expected']}个, "
        f"预测{aspect_result['total_predicted']}个"
    )

    # ── 5. 差评归因评测 ──
    print("\n5. 差评归因评测:")
    reason_result = evaluate_negative_reasons(benchmark_data)
    print(f"   精确率(Precision): {reason_result['precision']:.4f}")
    print(f"   召回率(Recall):    {reason_result['recall']:.4f}")
    print(f"   F1值(F1-Score):    {reason_result['f1']:.4f}")
    print(f"   统计: TP={reason_result['tp']}, FP={reason_result['fp']}, FN={reason_result['fn']}")
    print(
        f"   标签: 期望{reason_result['total_expected']}个, "
        f"预测{reason_result['total_predicted']}个"
    )

    # ── 6. 误差分析报告 ──
    print("\n6. 误差分析报告:")
    print(generate_error_report(sentiment_result))

    print("\n" + "=" * 60)
    print("评测完成")
    print("=" * 60)


if __name__ == "__main__":
    main()

