import json
import sys
import os
from collections import Counter
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analytics import AspectExtractor, SentimentResult


def load_benchmark(filepath: str) -> List[Dict]:
    data = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data


def evaluate_aspect_extraction(benchmark_data: List[Dict]) -> Dict:
    total_samples = len(benchmark_data)
    tp_aspect = 0
    fp_aspect = 0
    fn_aspect = 0
    total_aspect_labels = 0
    predicted_aspect_labels = 0

    for sample in benchmark_data:
        text = sample['content']
        expected_aspects = set(sample['aspect_labels'])
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
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'tp': tp_aspect,
        'fp': fp_aspect,
        'fn': fn_aspect,
        'total_expected': total_aspect_labels,
        'total_predicted': predicted_aspect_labels,
    }


def evaluate_negative_reasons(benchmark_data: List[Dict]) -> Dict:
    negative_samples = [s for s in benchmark_data if s['sentiment'] == 'NEGATIVE']
    total_samples = len(negative_samples)
    tp_reason = 0
    fp_reason = 0
    fn_reason = 0
    total_reason_labels = 0
    predicted_reason_labels = 0

    for sample in negative_samples:
        text = sample['content']
        expected_reasons = set(sample['negative_reason'])
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
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'tp': tp_reason,
        'fp': fp_reason,
        'fn': fn_reason,
        'total_expected': total_reason_labels,
        'total_predicted': predicted_reason_labels,
        'negative_samples': total_samples,
    }


def analyze_sentiment_distribution(benchmark_data: List[Dict]) -> Dict:
    distribution = Counter(s['sentiment'] for s in benchmark_data)
    return dict(distribution)


def main():
    benchmark_path = 'tests/data/benchmark_reviews.jsonl'

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

    print("\n3. 方面词提取评测:")
    aspect_result = evaluate_aspect_extraction(benchmark_data)
    print(f"   精确率(Precision): {aspect_result['precision']:.4f}")
    print(f"   召回率(Recall):    {aspect_result['recall']:.4f}")
    print(f"   F1值(F1-Score):    {aspect_result['f1']:.4f}")
    print(f"   统计: TP={aspect_result['tp']}, FP={aspect_result['fp']}, FN={aspect_result['fn']}")
    print(f"   标签: 期望{aspect_result['total_expected']}个, 预测{aspect_result['total_predicted']}个")

    print("\n4. 差评归因评测:")
    reason_result = evaluate_negative_reasons(benchmark_data)
    print(f"   精确率(Precision): {reason_result['precision']:.4f}")
    print(f"   召回率(Recall):    {reason_result['recall']:.4f}")
    print(f"   F1值(F1-Score):    {reason_result['f1']:.4f}")
    print(f"   统计: TP={reason_result['tp']}, FP={reason_result['fp']}, FN={reason_result['fn']}")
    print(f"   标签: 期望{reason_result['total_expected']}个, 预测{reason_result['total_predicted']}个")

    print("\n5. 注意事项:")
    print("   - 由于网络环境限制，SentimentClassifier 无法加载 HuggingFace 模型")
    print("   - 情感分类功能需在网络可用时进行完整评测")
    print("   - 当前评测仅覆盖方面词提取和差评归因模块")

    print("\n" + "=" * 60)
    print("评测完成")
    print("=" * 60)


if __name__ == "__main__":
    main()