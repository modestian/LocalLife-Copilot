"""发布门禁检查器。

具体设计 §9.4：新模型必须在固定测试集不低于基线，关键负面召回不得下降；
通过人工抽检后才可登记。
ST-502 验收准则 ⑤：只有 APPROVED 版本可部署。

执行 4 项门禁检查，决定模型版本是否可以从 EVALUATED → APPROVED：
1. 评测门禁全部通过
2. 模型卡必填字段齐全
3. 人工抽检已完成（至少 20 条已审）
4. Adapter SHA-256 与训练快照一致
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from evaluation.model_card import REQUIRED_MODEL_CARD_FIELDS

logger = logging.getLogger(__name__)

# 人工抽检最少完成数量
MIN_HUMAN_REVIEWS = 20

# 人工抽检评分必填维度
REQUIRED_REVIEW_SCORES = (
    "factual",
    "relevance",
    "politeness",
    "safety",
    "no_prohibited_promises",
)


@dataclass(frozen=True, slots=True)
class GateCheckResult:
    """单项门禁检查结果。"""

    name: str
    description: str
    passed: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PublishingGateResult:
    """发布门禁总体结果。"""

    passed: bool
    checks: list[GateCheckResult] = field(default_factory=list)
    decision: str = "REJECTED"
    """APPROVED 或 REJECTED。"""

    @property
    def failed_checks(self) -> list[GateCheckResult]:
        """未通过的门禁检查列表。"""
        return [c for c in self.checks if not c.passed]

    @property
    def reasons(self) -> list[str]:
        """未通过原因列表。"""
        return [c.reason for c in self.failed_checks]


class PublishingGate:
    """发布门禁检查器。

    检查模型卡完整性、评测门禁、人工抽检和 adapter hash 一致性，
    决定模型版本是否可以审批发布。
    """

    def check(
        self,
        model_card: dict,
        eval_report: dict,
        human_reviews: list[dict],
        *,
        training_snapshot: dict | None = None,
        skip_human_review: bool = False,
    ) -> PublishingGateResult:
        """执行全部门禁检查。

        Args:
            model_card: 模型卡字典。
            eval_report: 评测报告字典。
            human_reviews: 人工抽检样本列表（含评分）。
            training_snapshot: 训练快照字典。如为 None 则跳过 adapter hash 校验。
            skip_human_review: 跳过人工抽检门禁（CI 环境）。

        Returns:
            PublishingGateResult 包含通过状态和各项检查详情。
        """
        checks: list[GateCheckResult] = []

        # 1. 评测门禁
        checks.append(self._check_evaluation_gate(eval_report))

        # 2. 模型卡完整性
        checks.append(self._check_model_card_complete(model_card))

        # 3. 人工抽检
        if skip_human_review:
            checks.append(
                GateCheckResult(
                    name="human_review_completed",
                    description="人工抽检已完成（>= 20 条已审）",
                    passed=True,
                    reason="已跳过（--skip-human-review）",
                )
            )
        else:
            checks.append(self._check_human_review_completed(human_reviews))

        # 4. Adapter hash 一致性
        if training_snapshot is not None:
            checks.append(self._check_adapter_hash(model_card, training_snapshot))
        else:
            checks.append(
                GateCheckResult(
                    name="adapter_hash_verified",
                    description="Adapter SHA-256 与训练快照一致",
                    passed=True,
                    reason="已跳过（无训练快照）",
                )
            )

        all_passed = all(c.passed for c in checks)
        decision = "APPROVED" if all_passed else "REJECTED"

        result = PublishingGateResult(
            passed=all_passed,
            checks=checks,
            decision=decision,
        )

        if all_passed:
            logger.info("Publishing gate PASSED — model can be APPROVED")
        else:
            logger.warning(
                "Publishing gate FAILED: %s",
                ", ".join(c.name for c in result.failed_checks),
            )

        return result

    def check_and_save(
        self,
        model_card: dict,
        eval_report: dict,
        human_reviews: list[dict],
        output_dir: str | Path,
        *,
        training_snapshot: dict | None = None,
        skip_human_review: bool = False,
    ) -> PublishingGateResult:
        """执行门禁检查并保存结果到 JSON。

        Args:
            model_card: 模型卡字典。
            eval_report: 评测报告字典。
            human_reviews: 人工抽检样本列表。
            output_dir: 输出目录。
            training_snapshot: 训练快照（可选）。
            skip_human_review: 跳过人工抽检门禁。

        Returns:
            PublishingGateResult。
        """
        result = self.check(
            model_card,
            eval_report,
            human_reviews,
            training_snapshot=training_snapshot,
            skip_human_review=skip_human_review,
        )

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        gate_path = output_dir / "publishing_gate_result.json"

        gate_data = {
            "passed": result.passed,
            "decision": result.decision,
            "checks": [
                {
                    "name": c.name,
                    "description": c.description,
                    "passed": c.passed,
                    "reason": c.reason,
                }
                for c in result.checks
            ],
            "failed_checks": [c.name for c in result.failed_checks],
            "checked_at": _now_iso(),
        }

        with gate_path.open("w", encoding="utf-8") as f:
            json.dump(gate_data, f, indent=2, ensure_ascii=False)

        logger.info("Publishing gate result saved to %s", gate_path)
        return result

    # ------------------------------------------------------------------
    # 内部检查方法
    # ------------------------------------------------------------------

    def _check_evaluation_gate(self, eval_report: dict) -> GateCheckResult:
        """检查 1：评测门禁全部通过。"""
        gate = eval_report.get("comparison", {}).get("gate", {})
        gate_passed = gate.get("gate_passed", False)

        if gate_passed:
            return GateCheckResult(
                name="evaluation_gate_passed",
                description=(
                    "评测门禁全部通过（负面召回不下降 + Macro-F1 不低于基线 + 提升 >= 0.03）"
                ),
                passed=True,
            )

        failed = [c["name"] for c in gate.get("checks", []) if not c.get("passed", False)]
        return GateCheckResult(
            name="evaluation_gate_passed",
            description="评测门禁全部通过",
            passed=False,
            reason=f"未通过项：{', '.join(failed)}" if failed else "门禁结果不可用",
        )

    def _check_model_card_complete(self, model_card: dict) -> GateCheckResult:
        """检查 2：模型卡必填字段齐全。"""
        missing = [field for field in REQUIRED_MODEL_CARD_FIELDS if field not in model_card]

        if not missing:
            return GateCheckResult(
                name="model_card_complete",
                description="模型卡必填字段齐全",
                passed=True,
            )

        return GateCheckResult(
            name="model_card_complete",
            description="模型卡必填字段齐全",
            passed=False,
            reason=f"缺失字段：{', '.join(missing)}",
        )

    def _check_human_review_completed(
        self,
        human_reviews: list[dict],
    ) -> GateCheckResult:
        """检查 3：人工抽检已完成（至少 MIN_HUMAN_REVIEWS 条已审）。"""
        reviewed_count = 0
        incomplete: list[int] = []

        for i, sample in enumerate(human_reviews):
            scores = sample.get("scores", {})
            all_filled = all(scores.get(dim) is not None for dim in REQUIRED_REVIEW_SCORES)
            if all_filled:
                reviewed_count += 1
            else:
                incomplete.append(i)

        if reviewed_count >= MIN_HUMAN_REVIEWS:
            return GateCheckResult(
                name="human_review_completed",
                description=f"人工抽检已完成（>= {MIN_HUMAN_REVIEWS} 条已审）",
                passed=True,
                reason=f"已审 {reviewed_count} 条",
            )

        return GateCheckResult(
            name="human_review_completed",
            description=f"人工抽检已完成（>= {MIN_HUMAN_REVIEWS} 条已审）",
            passed=False,
            reason=(
                f"仅完成 {reviewed_count}/{len(human_reviews)} 条，需至少 {MIN_HUMAN_REVIEWS} 条"
            ),
        )

    def _check_adapter_hash(
        self,
        model_card: dict,
        training_snapshot: dict,
    ) -> GateCheckResult:
        """检查 4：Adapter SHA-256 与训练快照一致。"""
        card_hash = model_card.get("adapter_sha256", "")
        snapshot_hash = training_snapshot.get("adapter_sha256", "")

        if not card_hash or card_hash == "unknown":
            return GateCheckResult(
                name="adapter_hash_verified",
                description="Adapter SHA-256 与训练快照一致",
                passed=False,
                reason="模型卡中 adapter_sha256 缺失或为 unknown",
            )

        if not snapshot_hash or snapshot_hash == "unknown":
            return GateCheckResult(
                name="adapter_hash_verified",
                description="Adapter SHA-256 与训练快照一致",
                passed=False,
                reason="训练快照中 adapter_sha256 缺失或为 unknown",
            )

        if card_hash == snapshot_hash:
            return GateCheckResult(
                name="adapter_hash_verified",
                description="Adapter SHA-256 与训练快照一致",
                passed=True,
                reason=f"SHA-256: {card_hash[:16]}...",
            )

        return GateCheckResult(
            name="adapter_hash_verified",
            description="Adapter SHA-256 与训练快照一致",
            passed=False,
            reason=f"模型卡 {card_hash[:16]}... != 快照 {snapshot_hash[:16]}...",
        )


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
