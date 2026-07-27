"""TK-502-04 单元测试：同集评测、误差分析和人工抽检。

验收准则③：基线与 LoRA 使用同一测试集，关键负面召回不得下降，
总体指标不得低于基线，目标 Macro-F1 提升 ≥ 0.03。
"""

from __future__ import annotations

import json

import pytest

from evaluation.error_analysis import ErrorAnalyzer, generate_error_report
from evaluation.evaluate_model import (
    GATE_MIN_MACRO_F1_IMPROVEMENT,
    LABELS,
    check_gates,
    evaluate_predictions,
    load_test_data,
    save_report,
)
from evaluation.human_review import (
    CORRECT_SAMPLES_PER_CLASS,
    HumanReviewGenerator,
)

# ── 指标计算测试 ───────────────────────────────────────────────


class TestEvaluatePredictions:
    def test_perfect_predictions(self):
        y_true = ["POSITIVE", "NEGATIVE", "NEUTRAL"] * 4
        y_pred = y_true.copy()
        result = evaluate_predictions(y_true, y_pred)
        assert result["accuracy"] == 1.0
        assert result["macro_f1"] == 1.0
        assert result["correct"] == 12
        assert len(result["misclassified"]) == 0

    def test_all_wrong(self):
        y_true = ["POSITIVE"] * 3
        y_pred = ["NEGATIVE"] * 3
        result = evaluate_predictions(y_true, y_pred)
        assert result["accuracy"] == 0.0
        assert result["macro_f1"] < 0.5
        assert len(result["misclassified"]) == 3

    def test_per_class_metrics(self):
        y_true = ["NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"]
        y_pred = ["NEGATIVE", "POSITIVE", "POSITIVE", "POSITIVE"]
        result = evaluate_predictions(y_true, y_pred)
        # POSITIVE: TP=2, FP=1, FN=0 → precision=2/3, recall=1.0
        assert result["per_class"]["POSITIVE"]["recall"] == 1.0
        # NEGATIVE: TP=1, FP=0, FN=1 → precision=1.0, recall=0.5
        assert result["per_class"]["NEGATIVE"]["precision"] == 1.0
        assert result["per_class"]["NEGATIVE"]["recall"] == 0.5

    def test_confusion_matrix(self):
        y_true = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
        y_pred = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
        result = evaluate_predictions(y_true, y_pred)
        cm = result["confusion_matrix"]
        assert cm["NEGATIVE"]["NEGATIVE"] == 1
        assert cm["NEUTRAL"]["NEUTRAL"] == 1
        assert cm["POSITIVE"]["POSITIVE"] == 1
        assert cm["NEGATIVE"]["POSITIVE"] == 0

    def test_negative_recall(self):
        y_true = ["NEGATIVE", "NEGATIVE", "POSITIVE"]
        y_pred = ["NEGATIVE", "POSITIVE", "POSITIVE"]
        result = evaluate_predictions(y_true, y_pred)
        assert result["negative_recall"] == 0.5

    def test_calibration_with_confidences(self):
        y_true = ["POSITIVE", "NEGATIVE", "NEUTRAL", "POSITIVE"]
        y_pred = ["POSITIVE", "NEGATIVE", "NEUTRAL", "POSITIVE"]
        confs = [0.95, 0.92, 0.55, 0.88]
        result = evaluate_predictions(y_true, y_pred, confs)
        assert result["calibration"] is not None
        assert "0.9-1.0" in result["calibration"]
        assert result["calibration"]["0.9-1.0"]["count"] == 2

    def test_calibration_none_without_confidences(self):
        y_true = ["POSITIVE", "NEGATIVE"]
        y_pred = ["POSITIVE", "NEGATIVE"]
        result = evaluate_predictions(y_true, y_pred)
        assert result["calibration"] is None

    def test_misclassified_includes_index(self):
        y_true = ["POSITIVE", "NEGATIVE"]
        y_pred = ["NEGATIVE", "NEGATIVE"]
        result = evaluate_predictions(y_true, y_pred)
        assert len(result["misclassified"]) == 1
        assert result["misclassified"][0]["index"] == 0
        assert result["misclassified"][0]["true"] == "POSITIVE"
        assert result["misclassified"][0]["pred"] == "NEGATIVE"


# ── 门禁检查测试 ───────────────────────────────────────────────


class TestGateChecks:
    def _make_result(self, macro_f1, neg_recall):
        return {
            "macro_f1": macro_f1,
            "negative_recall": neg_recall,
            "accuracy": 0.9,
            "per_class": {
                lbl: {"precision": 0.9, "recall": 0.9, "f1": 0.9, "support": 10} for lbl in LABELS
            },
        }

    def test_all_gates_pass(self):
        baseline = self._make_result(0.90, 0.85)
        lora = self._make_result(0.95, 0.90)
        gate = check_gates(baseline, lora)
        assert gate["gate_passed"] is True
        assert len(gate["checks"]) == 3
        assert all(c["passed"] for c in gate["checks"])

    def test_negative_recall_decreased_fails(self):
        baseline = self._make_result(0.90, 0.90)
        lora = self._make_result(0.95, 0.85)
        gate = check_gates(baseline, lora)
        assert gate["gate_passed"] is False
        neg_check = next(c for c in gate["checks"] if c["name"] == "negative_recall_not_decreased")
        assert neg_check["passed"] is False

    def test_macro_f1_below_baseline_fails(self):
        baseline = self._make_result(0.95, 0.90)
        lora = self._make_result(0.90, 0.90)
        gate = check_gates(baseline, lora)
        f1_check = next(c for c in gate["checks"] if c["name"] == "macro_f1_not_below_baseline")
        assert f1_check["passed"] is False

    def test_macro_f1_improvement_below_threshold_fails(self):
        baseline = self._make_result(0.90, 0.90)
        lora = self._make_result(0.92, 0.90)
        gate = check_gates(baseline, lora)
        target_check = next(
            c for c in gate["checks"] if c["name"] == "macro_f1_improvement_ge_0.03"
        )
        assert target_check["passed"] is False
        assert target_check["threshold"] == GATE_MIN_MACRO_F1_IMPROVEMENT

    def test_macro_f1_improvement_at_threshold_passes(self):
        baseline = self._make_result(0.90, 0.90)
        lora = self._make_result(0.90 + GATE_MIN_MACRO_F1_IMPROVEMENT, 0.90)
        gate = check_gates(baseline, lora)
        target_check = next(
            c for c in gate["checks"] if c["name"] == "macro_f1_improvement_ge_0.03"
        )
        assert target_check["passed"] is True

    def test_gate_summary_includes_deltas(self):
        baseline = self._make_result(0.90, 0.85)
        lora = self._make_result(0.95, 0.88)
        gate = check_gates(baseline, lora)
        assert "macro_f1_delta" in gate["summary"]
        assert "negative_recall_delta" in gate["summary"]
        assert gate["summary"]["macro_f1_delta"] == 0.05
        assert gate["summary"]["negative_recall_delta"] == 0.03


# ── 误差分析测试 ───────────────────────────────────────────────


class TestErrorAnalyzer:
    @pytest.fixture
    def test_data(self):
        return [{"text": f"sample {i}", "sentiment": LABELS[i % 3]} for i in range(6)]

    @pytest.fixture
    def baseline_result(self):
        return {
            "misclassified": [
                {"index": 0, "true": "NEGATIVE", "pred": "NEUTRAL", "confidence": 0.6},
                {"index": 1, "true": "NEUTRAL", "pred": "POSITIVE", "confidence": 0.85},
            ],
            "total": 6,
            "correct": 4,
        }

    @pytest.fixture
    def lora_result(self):
        return {
            "misclassified": [
                # Index 1: both wrong, but different prediction → disagreement
                {"index": 1, "true": "NEUTRAL", "pred": "NEGATIVE", "confidence": 0.9},
                {"index": 2, "true": "POSITIVE", "pred": "NEGATIVE", "confidence": 0.7},
            ],
            "total": 6,
            "correct": 4,
        }

    def test_improvements_detected(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        # Index 0: baseline wrong, lora correct → improvement
        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["index"] == 0

    def test_regressions_detected(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        # Index 2: baseline correct, lora wrong → regression
        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["index"] == 2

    def test_disagreements_detected(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        # Index 1: both wrong, different predictions → disagreement
        assert len(result["disagreements"]) == 1
        assert result["disagreements"][0]["index"] == 1

    def test_error_direction_stats(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        assert "NEGATIVE→NEUTRAL" in result["error_direction_stats"]["baseline"]
        assert "NEUTRAL→POSITIVE" in result["error_direction_stats"]["baseline"]

    def test_high_confidence_errors(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        # baseline has 1 high-conf error (0.85)
        assert len(result["high_confidence_errors"]["baseline"]) == 1
        # lora has 1 high-conf error (0.9)
        assert len(result["high_confidence_errors"]["lora"]) == 1

    def test_summary_counts(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        result = analyzer.analyze()
        s = result["summary"]
        assert s["total_test_samples"] == 6
        assert s["baseline_errors"] == 2
        assert s["lora_errors"] == 2
        assert s["improvements"] == 1
        assert s["regressions"] == 1
        assert s["disagreements"] == 1
        assert s["net_improvement"] == 0

    def test_generate_error_report_returns_string(self, test_data, baseline_result, lora_result):
        analyzer = ErrorAnalyzer(test_data, baseline_result, lora_result)
        ea = analyzer.analyze()
        report = generate_error_report(ea, baseline_result, lora_result)
        assert isinstance(report, str)
        assert "总测试样本" in report
        assert "改善样本" in report


# ── 人工抽检测试 ───────────────────────────────────────────────


class TestHumanReviewGenerator:
    @pytest.fixture
    def test_data(self):
        return [{"text": f"text_{i}", "sentiment": LABELS[i % 3]} for i in range(30)]

    @pytest.fixture
    def baseline_result(self):
        return {
            "misclassified": [
                {"index": 0, "true": "NEGATIVE", "pred": "NEUTRAL", "confidence": 0.6},
                {"index": 5, "true": "NEUTRAL", "pred": "NEGATIVE", "confidence": 0.55},
            ],
            "total": 30,
            "correct": 28,
        }

    @pytest.fixture
    def lora_result(self):
        return {
            "misclassified": [
                {"index": 0, "true": "NEGATIVE", "pred": "NEUTRAL", "confidence": 0.65},
                {"index": 10, "true": "POSITIVE", "pred": "NEGATIVE", "confidence": 0.9},
            ],
            "total": 30,
            "correct": 28,
        }

    def test_includes_all_error_samples(self, test_data, baseline_result, lora_result):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        sample_ids = {s["sample_id"] for s in samples}
        # Index 0 (both wrong), 5 (baseline only), 10 (lora only)
        assert 0 in sample_ids
        assert 5 in sample_ids
        assert 10 in sample_ids

    def test_includes_boundary_samples(self, test_data, baseline_result, lora_result):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        # Index 5 has confidence 0.55 (boundary), index 0 has 0.6/0.65 (boundary)
        sample_ids = {s["sample_id"] for s in samples}
        assert 5 in sample_ids

    def test_includes_correct_samples_per_class(self, test_data, baseline_result, lora_result):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        correct_samples = [s for s in samples if s["sample_type"] == "correct"]
        # Should have up to CORRECT_SAMPLES_PER_CLASS per class
        by_class: dict[str, int] = {}
        for s in correct_samples:
            by_class[s["true_label"]] = by_class.get(s["true_label"], 0) + 1
        for label in LABELS:
            assert by_class.get(label, 0) <= CORRECT_SAMPLES_PER_CLASS

    def test_sample_has_review_criteria(self, test_data, baseline_result, lora_result):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        assert len(samples) > 0
        s = samples[0]
        assert "review_criteria" in s
        rc = s["review_criteria"]
        assert "factual_accuracy" in rc
        assert "relevance" in rc
        assert "politeness" in rc
        assert "safety" in rc
        assert "banned_commitment_check" in rc
        assert rc["factual_accuracy"] is None  # 未填写

    def test_sample_type_labels(self, test_data, baseline_result, lora_result):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        types = {s["sample_type"] for s in samples}
        # Should have at least "both_wrong" (index 0) and "correct" samples
        assert "both_wrong" in types or "improvement" in types or "regression" in types

    def test_reproducible_with_seed(self, test_data, baseline_result, lora_result):
        gen1 = HumanReviewGenerator(test_data, baseline_result, lora_result, seed=42)
        gen2 = HumanReviewGenerator(test_data, baseline_result, lora_result, seed=42)
        s1 = gen1.generate()
        s2 = gen2.generate()
        assert [s["sample_id"] for s in s1] == [s["sample_id"] for s in s2]

    def test_save_to_jsonl(self, test_data, baseline_result, lora_result, tmp_path):
        gen = HumanReviewGenerator(test_data, baseline_result, lora_result)
        samples = gen.generate()
        output = tmp_path / "review.jsonl"
        gen.save(samples, str(output))
        assert output.exists()
        lines = output.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(samples)
        first = json.loads(lines[0])
        assert "sample_id" in first
        assert "review_criteria" in first


# ── 报告保存测试 ───────────────────────────────────────────────


class TestSaveReport:
    def test_save_json_and_markdown(self, tmp_path):
        report = {
            "job_id": "test-001",
            "test_set": "test.jsonl",
            "evaluated_at": "2026-01-01T00:00:00Z",
            "baseline": {
                "model": "base",
                "macro_f1": 0.90,
                "accuracy": 0.92,
                "negative_recall": 0.85,
                "per_class": {
                    "NEGATIVE": {"precision": 0.9, "recall": 0.85, "f1": 0.87, "support": 10},
                },
            },
            "lora": {
                "model": "base",
                "adapter_sha256": "abc123",
                "macro_f1": 0.95,
                "accuracy": 0.96,
                "negative_recall": 0.90,
                "per_class": {
                    "NEGATIVE": {"precision": 0.95, "recall": 0.90, "f1": 0.92, "support": 10},
                },
            },
            "comparison": {
                "macro_f1_delta": 0.05,
                "negative_recall_delta": 0.05,
                "gate": {
                    "gate_passed": True,
                    "checks": [
                        {
                            "name": "negative_recall_not_decreased",
                            "baseline_value": 0.85,
                            "lora_value": 0.90,
                            "delta": 0.05,
                            "passed": True,
                        }
                    ],
                    "summary": {"all_passed": True},
                },
            },
        }

        json_path = save_report(report, "test-001", tmp_path)
        assert json_path.exists()
        assert json_path.name == "evaluation_report.json"

        md_path = json_path.parent / "evaluation_report.md"
        assert md_path.exists()
        md_content = md_path.read_text(encoding="utf-8")
        assert "同集评测报告" in md_content
        assert "test-001" in md_content
        assert "门禁结果" in md_content

    def test_save_creates_directory(self, tmp_path):
        report = {"job_id": "test-002", "baseline": {}, "lora": {}, "comparison": {}}
        output_dir = tmp_path / "nested" / "reports"
        json_path = save_report(report, "test-002", output_dir)
        assert json_path.exists()


# ── 加载测试数据测试 ───────────────────────────────────────────


class TestLoadTestData:
    def test_load_jsonl_with_int_labels(self, tmp_path):
        path = tmp_path / "test.jsonl"
        path.write_text(
            '{"text": "好吃", "label": 2}\n{"text": "难吃", "label": 0}\n',
            encoding="utf-8",
        )
        data = load_test_data(str(path))
        assert len(data) == 2
        assert data[0]["sentiment"] == "POSITIVE"
        assert data[1]["sentiment"] == "NEGATIVE"

    def test_load_jsonl_with_sentiment_field(self, tmp_path):
        path = tmp_path / "test.jsonl"
        path.write_text(
            '{"content": "好吃", "sentiment": "POSITIVE"}\n',
            encoding="utf-8",
        )
        data = load_test_data(str(path))
        assert len(data) == 1
        assert data[0]["sentiment"] == "POSITIVE"

    def test_load_skips_empty_lines(self, tmp_path):
        path = tmp_path / "test.jsonl"
        path.write_text(
            '{"text": "好吃", "label": 2}\n\n{"text": "难吃", "label": 0}\n',
            encoding="utf-8",
        )
        data = load_test_data(str(path))
        assert len(data) == 2


# ── Adapter 加载器 Protocol 满足性测试 ──────────────────────────


class TestAdapterLoaderProtocol:
    def test_satisfies_model_adapter_protocol(self):
        """验证 LoRAAdapterLoader 满足 ModelAdapter Protocol。"""
        from evaluation.adapter_loader import LoRAAdapterLoader

        loader = LoRAAdapterLoader(
            base_model_id="uer/roberta-base-finetuned-dianping-chinese",
            adapter_dir="/tmp/fake",
        )
        # Protocol 接口存在性检查（不调用 load()）
        assert hasattr(type(loader), "model_version")
        assert hasattr(type(loader), "predict")
        assert callable(getattr(loader, "predict", None))
