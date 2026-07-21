"""TK-502-05 单元测试：模型卡生成和发布门禁。

验收准则 ④：模型卡记录数据、配置、指标、限制和人工抽检结论。
验收准则 ⑤：只有 APPROVED 版本可部署。
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.model_card import REQUIRED_MODEL_CARD_FIELDS, ModelCardGenerator
from evaluation.publishing_gate import (
    MIN_HUMAN_REVIEWS,
    PublishingGate,
)

# ── 测试夹具 ─────────────────────────────────────────────────────


def _make_eval_report(
    *,
    gate_passed: bool = True,
    baseline_f1: float = 0.122,
    lora_f1: float = 0.9851,
    neg_recall_delta: float = 0.9773,
    lora_errors: int = 2,
    regressions: int = 0,
    high_conf_lora_errors: list | None = None,
) -> dict:
    """构造评测报告字典。"""
    if high_conf_lora_errors is None:
        high_conf_lora_errors = [
            {"index": 3, "true": "NEGATIVE", "pred": "POSITIVE", "confidence": 0.9814},
            {"index": 132, "true": "POSITIVE", "pred": "NEUTRAL", "confidence": 0.9848},
        ]

    return {
        "job_id": "test-job",
        "test_set": "test.jsonl",
        "evaluated_at": "2026-07-21T09:00:00+00:00",
        "baseline": {
            "model": "uer/roberta-base-finetuned-dianping-chinese",
            "accuracy": 0.2239,
            "macro_f1": baseline_f1,
            "negative_recall": 0.0,
            "per_class": {
                "NEGATIVE": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 44},
                "NEUTRAL": {"precision": 0.2239, "recall": 1.0, "f1": 0.3659, "support": 30},
                "POSITIVE": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 60},
            },
            "confusion_matrix": {},
            "calibration": {},
            "total": 134,
            "correct": 30,
        },
        "lora": {
            "model": "uer/roberta-base-finetuned-dianping-chinese",
            "adapter_sha256": "8f43de23f807756bcf9ae416c37ffddb26ed14f151469012144f67d87b2256b6",
            "accuracy": 0.9851,
            "macro_f1": lora_f1,
            "negative_recall": 0.9773,
            "per_class": {
                "NEGATIVE": {"precision": 1.0, "recall": 0.9773, "f1": 0.9885, "support": 44},
                "NEUTRAL": {"precision": 0.9677, "recall": 1.0, "f1": 0.9836, "support": 30},
                "POSITIVE": {"precision": 0.9833, "recall": 0.9833, "f1": 0.9833, "support": 60},
            },
            "confusion_matrix": {},
            "calibration": {},
            "total": 134,
            "correct": 132,
        },
        "comparison": {
            "macro_f1_delta": round(lora_f1 - baseline_f1, 4),
            "negative_recall_delta": neg_recall_delta,
            "gate": {
                "gate_passed": gate_passed,
                "checks": [
                    {
                        "name": "negative_recall_not_decreased",
                        "baseline_value": 0.0,
                        "lora_value": 0.9773,
                        "delta": neg_recall_delta,
                        "passed": gate_passed,
                    },
                    {
                        "name": "macro_f1_not_below_baseline",
                        "baseline_value": baseline_f1,
                        "lora_value": lora_f1,
                        "delta": round(lora_f1 - baseline_f1, 4),
                        "passed": gate_passed,
                    },
                    {
                        "name": "macro_f1_improvement_ge_0.03",
                        "baseline_value": baseline_f1,
                        "lora_value": lora_f1,
                        "delta": round(lora_f1 - baseline_f1, 4),
                        "threshold": 0.03,
                        "passed": gate_passed,
                    },
                ],
                "summary": {
                    "macro_f1_delta": round(lora_f1 - baseline_f1, 4),
                    "negative_recall_delta": neg_recall_delta,
                    "all_passed": gate_passed,
                },
            },
            "summary": {
                "macro_f1_delta": round(lora_f1 - baseline_f1, 4),
                "negative_recall_delta": neg_recall_delta,
                "all_passed": gate_passed,
            },
        },
        "error_analysis": {
            "improvements": [],
            "regressions": [],
            "disagreements": [],
            "misclass_directions": {
                "baseline": {"POSITIVE->NEUTRAL": 60, "NEGATIVE->NEUTRAL": 44},
                "lora": {"NEGATIVE->POSITIVE": 1, "POSITIVE->NEUTRAL": 1},
            },
            "high_confidence_errors": {
                "baseline": [],
                "lora": high_conf_lora_errors,
            },
            "summary": {
                "total_test_samples": 134,
                "baseline_errors": 104,
                "lora_errors": lora_errors,
                "improvements": 102,
                "regressions": regressions,
                "disagreements": 1,
                "net_improvement": 102,
            },
        },
        "error_analysis_report": "test report",
    }


def _make_training_snapshot(
    *,
    smoke_mode: bool = False,
    adapter_sha256: str = "8f43de23f807756bcf9ae416c37ffddb26ed14f151469012144f67d87b2256b6",
) -> dict:
    """构造训练快照字典。"""
    return {
        "training_config": {
            "task_type": "sentiment_classification",
            "base_model_id": "uer/roberta-base-finetuned-dianping-chinese",
            "dataset_id": "local-dataset-v1",
            "method": "LORA",
            "hyperparameters": {
                "r": 8,
                "lora_alpha": 16,
                "lora_dropout": 0.05,
                "learning_rate": 0.0002,
                "epochs": 3,
                "batch_size": 16,
                "seed": 42,
            },
            "smoke_mode": smoke_mode,
        },
        "hyperparameter_hash": "abc123",
        "git_commit": "0211a6338abbfe8f4b3f9399d4f54954c42323f1",
        "dependencies": {
            "torch": "2.13.0+cpu",
            "transformers": "5.14.1",
            "peft": "0.19.1",
        },
        "metrics": {
            "eval_loss": 0.045,
            "eval_accuracy": 0.9925,
            "eval_f1_macro": 0.9934,
        },
        "dataset_files": {
            "train": "backend/training/data/train.jsonl",
            "val": "backend/training/data/val.jsonl",
            "test": "backend/training/data/test.jsonl",
        },
        "adapter_sha256": adapter_sha256,
    }


def _make_human_reviews(
    count: int,
    *,
    reviewed: int = 0,
) -> list[dict]:
    """构造人工抽检样本列表。

    Args:
        count: 总样本数。
        reviewed: 已完成评分的数量（其余样本 scores 为空）。
    """
    samples = []
    for i in range(count):
        sample = {
            "index": i,
            "text": f"测试样本 {i}",
            "true_label": "POSITIVE",
            "baseline_pred": "NEUTRAL",
            "lora_pred": "POSITIVE",
        }
        if i < reviewed:
            sample["scores"] = {
                "factual": 4,
                "relevance": 5,
                "politeness": 4,
                "safety": 5,
                "no_prohibited_promises": True,
            }
            sample["review_notes"] = "测试备注"
        else:
            sample["scores"] = {}
        samples.append(sample)
    return samples


# ── ModelCardGenerator 测试 ──────────────────────────────────────


class TestModelCardGenerator:
    """模型卡生成器测试。"""

    def test_all_fields_populated(self):
        """所有必填字段都正确填充。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        reviews = _make_human_reviews(30, reviewed=25)

        gen = ModelCardGenerator(job_id="test-job", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=reviews,
        )

        for field in REQUIRED_MODEL_CARD_FIELDS:
            assert field in card, f"缺失必填字段: {field}"

    def test_model_metadata_correct(self):
        """模型元数据正确。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="lora-001", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert card["model_name"] == "sentiment-roberta-lora"
        assert card["version"] == "lora-001"
        assert card["task_type"] == "sentiment_classification"
        assert card["base_model_ref"] == "uer/roberta-base-finetuned-dianping-chinese"
        assert card["method"] == "LORA"
        assert card["adapter_sha256"] == snapshot["adapter_sha256"]

    def test_training_info_populated(self):
        """训练信息区块正确填充。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        training = card["training"]
        assert training["git_commit"] == snapshot["git_commit"]
        assert training["dependencies"] == snapshot["dependencies"]
        assert training["smoke_mode"] is False
        assert training["hyperparameters"]["r"] == 8
        assert training["training_metrics"]["eval_accuracy"] == 0.9925

    def test_metrics_correct(self):
        """评测指标区块正确提取。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        metrics = card["metrics"]
        assert metrics["baseline_macro_f1"] == 0.122
        assert metrics["lora_macro_f1"] == 0.9851
        assert metrics["macro_f1_delta"] == 0.8631
        assert metrics["baseline_negative_recall"] == 0.0
        assert metrics["lora_negative_recall"] == 0.9773
        assert "NEGATIVE" in metrics["per_class"]

    def test_gate_result_propagated(self):
        """门禁结果正确传播到模型卡。"""
        eval_report = _make_eval_report(gate_passed=True)
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert card["gate_result"]["gate_passed"] is True
        assert len(card["gate_result"]["checks"]) == 3

    def test_gate_failed_propagated(self):
        """门禁未通过时正确传播。"""
        eval_report = _make_eval_report(gate_passed=False, baseline_f1=0.99, lora_f1=0.98)
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert card["gate_result"]["gate_passed"] is False

    def test_limitations_auto_generated(self):
        """限制说明自动生成。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        limitations = card["limitations"]
        assert len(limitations) > 0

        # 应包含基线模型架构限制
        assert any("2 分类" in lim for lim in limitations)

        # 应包含高置信度错分限制
        assert any("高置信度错分" in lim for lim in limitations)
        assert any("2 条" in lim for lim in limitations)

    def test_limitations_smoke_mode(self):
        """smoke 模式时生成对应限制。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot(smoke_mode=True)

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert any("smoke" in lim.lower() for lim in card["limitations"])

    def test_limitations_regressions(self):
        """退化样本时生成对应限制。"""
        eval_report = _make_eval_report(regressions=3)
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert any("退化" in lim and "3" in lim for lim in card["limitations"])

    def test_limitations_no_high_conf_errors(self):
        """无高置信度错分时不生成对应限制。"""
        eval_report = _make_eval_report(high_conf_lora_errors=[])
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert not any("高置信度错分" in lim for lim in card["limitations"])

    def test_human_review_summary(self):
        """人工抽检摘要正确。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        reviews = _make_human_reviews(50, reviewed=20)

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=reviews,
        )

        hr = card["human_review"]
        assert hr["total_samples"] == 50
        assert hr["reviewed"] == 20
        assert "20/50" in hr["review_summary"]

    def test_human_review_all_completed(self):
        """全部抽检完成时摘要正确。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        reviews = _make_human_reviews(10, reviewed=10)

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=reviews,
        )

        assert card["human_review"]["reviewed"] == 10
        assert "全部" in card["human_review"]["review_summary"]

    def test_missing_training_snapshot(self):
        """训练快照缺失时降级处理。"""
        eval_report = _make_eval_report()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot={},
            human_review_samples=[],
        )

        assert card["training"]["git_commit"] == "unknown"
        assert card["training"]["dependencies"] == {}
        assert card["training"]["hyperparameters"] == {}
        # adapter_sha256 从 eval_report 降级获取
        assert card["adapter_sha256"] == eval_report["lora"]["adapter_sha256"]

    def test_generated_at_present(self):
        """模型卡包含生成时间戳。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent")
        card = gen.generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert "generated_at" in card
        assert "T" in card["generated_at"]

    def test_generate_and_save(self, tmp_path: Path):
        """生成并保存模型卡 JSON 文件。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()

        gen = ModelCardGenerator(job_id="test-job", artifact_root="/tmp/nonexistent")
        result = gen.generate_and_save(
            eval_report=eval_report,
            output_dir=tmp_path,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        assert Path(result.output_path).exists()
        with Path(result.output_path).open(encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["model_name"] == "sentiment-roberta-lora"


# ── PublishingGate 测试 ─────────────────────────────────────────


class TestPublishingGate:
    """发布门禁检查器测试。"""

    def test_all_pass_approved(self):
        """全部通过时 APPROVED。"""
        eval_report = _make_eval_report(gate_passed=True)
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        assert result.passed is True
        assert result.decision == "APPROVED"
        assert len(result.failed_checks) == 0

    def test_evaluation_gate_failed(self):
        """评测门禁未通过时 REJECTED。"""
        eval_report = _make_eval_report(gate_passed=False, baseline_f1=0.99, lora_f1=0.98)
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        assert result.passed is False
        assert result.decision == "REJECTED"
        assert any(c.name == "evaluation_gate_passed" for c in result.failed_checks)

    def test_model_card_incomplete(self):
        """模型卡字段缺失时 REJECTED。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        reviews = _make_human_reviews(30, reviewed=25)

        # 缺少 limitations 字段
        card = {"model_name": "test", "version": "v1"}

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        assert result.passed is False
        assert any(c.name == "model_card_complete" for c in result.failed_checks)

    def test_human_review_insufficient(self):
        """人工抽检不足 20 条时 REJECTED。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=5)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        assert result.passed is False
        assert any(c.name == "human_review_completed" for c in result.failed_checks)

    def test_human_review_exactly_min(self):
        """恰好 20 条已审时通过。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(25, reviewed=MIN_HUMAN_REVIEWS)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        human_check = next(c for c in result.checks if c.name == "human_review_completed")
        assert human_check.passed is True

    def test_human_review_incomplete_scores(self):
        """部分评分维度未填写时不计入已审。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )

        # 恰好 20 条已审，删除 1 个评分维度后变为 19 条，低于阈值
        reviews = _make_human_reviews(25, reviewed=MIN_HUMAN_REVIEWS)
        reviews[0]["scores"].pop("safety")

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        human_check = next(c for c in result.checks if c.name == "human_review_completed")
        assert human_check.passed is False

    def test_adapter_hash_mismatch(self):
        """adapter SHA-256 不一致时 REJECTED。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot(
            adapter_sha256="aaa111",
        )
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        # 模型卡中的 hash 来自 snapshot，但我们传一个不同的 snapshot 来检查
        different_snapshot = _make_training_snapshot(
            adapter_sha256="bbb222",
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=different_snapshot,
        )

        assert result.passed is False
        assert any(c.name == "adapter_hash_verified" for c in result.failed_checks)

    def test_adapter_hash_match(self):
        """adapter SHA-256 一致时通过。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        hash_check = next(c for c in result.checks if c.name == "adapter_hash_verified")
        assert hash_check.passed is True

    def test_skip_human_review(self):
        """--skip-human-review 时跳过人工抽检门禁。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = []  # 无任何抽检

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
            skip_human_review=True,
        )

        human_check = next(c for c in result.checks if c.name == "human_review_completed")
        assert human_check.passed is True
        assert "跳过" in human_check.reason

    def test_no_training_snapshot_skips_hash(self):
        """无训练快照时跳过 hash 校验。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=None,
        )

        hash_check = next(c for c in result.checks if c.name == "adapter_hash_verified")
        assert hash_check.passed is True

    def test_multiple_failures(self):
        """多项同时失败时全部报告。"""
        eval_report = _make_eval_report(gate_passed=False, baseline_f1=0.99, lora_f1=0.98)
        snapshot = _make_training_snapshot(adapter_sha256="aaa111")
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        different_snapshot = _make_training_snapshot(adapter_sha256="bbb222")
        reviews = _make_human_reviews(10, reviewed=0)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=different_snapshot,
        )

        assert result.passed is False
        assert result.decision == "REJECTED"
        assert len(result.failed_checks) >= 3  # 评测 + 人工 + hash

    def test_check_and_save(self, tmp_path: Path):
        """门禁结果保存到 JSON 文件。"""
        eval_report = _make_eval_report()
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(30, reviewed=25)

        gate = PublishingGate()
        gate.check_and_save(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            output_dir=tmp_path,
            training_snapshot=snapshot,
        )

        gate_path = tmp_path / "publishing_gate_result.json"
        assert gate_path.exists()
        with gate_path.open(encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["decision"] == "APPROVED"
        assert len(saved["checks"]) == 4

    def test_reasons_property(self):
        """reasons 属性返回未通过原因列表。"""
        eval_report = _make_eval_report(gate_passed=False, baseline_f1=0.99, lora_f1=0.98)
        snapshot = _make_training_snapshot()
        card = ModelCardGenerator(job_id="test", artifact_root="/tmp/nonexistent").generate(
            eval_report=eval_report,
            training_snapshot=snapshot,
            human_review_samples=[],
        )
        reviews = _make_human_reviews(10, reviewed=0)

        gate = PublishingGate()
        result = gate.check(
            model_card=card,
            eval_report=eval_report,
            human_reviews=reviews,
            training_snapshot=snapshot,
        )

        assert len(result.reasons) >= 2
        assert all(isinstance(r, str) for r in result.reasons)
