"""模型版本、部署和训练任务状态枚举常量。

符合数据库约束 §11.8 的 CHECK 约束值。
"""

# 模型版本状态（数据库约束 §11.8 model_versions.status）
# 只有 APPROVED 版本可部署。
MODEL_VERSION_STATUSES: frozenset[str] = frozenset(
    {
        "REGISTERED",  # 刚登记，未评测
        "EVALUATED",  # 已完成评测
        "APPROVED",  # 通过审批门禁
        "REJECTED",  # 未通过门禁
        "ARCHIVED",  # 归档
    }
)

# 可部署的模型版本状态
DEPLOYABLE_STATUSES: frozenset[str] = frozenset({"APPROVED"})

# 部署状态（数据库约束 §11.8 model_deployments.status）
DEPLOYMENT_STATUSES: frozenset[str] = frozenset(
    {
        "ACTIVE",  # 全量生效
        "CANARY",  # 灰度
        "SUPERSEDED",  # 已被新版本替换
        "ROLLED_BACK",  # 已回滚
    }
)

# 训练任务状态（数据库约束 §4.5 fine_tuning_jobs.status）
# 状态只允许 PENDING → RUNNING → SUCCEEDED|FAILED|CANCELLED
JOB_STATUSES: frozenset[str] = frozenset(
    {
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
    }
)

# 数据集状态（数据库约束 §11.8 datasets.status）
# 只有 READY 可用于训练。
DATASET_STATUSES: frozenset[str] = frozenset(
    {
        "BUILDING",
        "READY",
        "REJECTED",
        "ARCHIVED",
    }
)

# 只有 READY 的数据集可用于训练
TRAINABLE_DATASET_STATUSES: frozenset[str] = frozenset({"READY"})
