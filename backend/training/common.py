"""训练脚本共享的常量、函数和 Trainer 子类。

被 train.py（全参数微调）和 train_lora.py（LoRA 微调）复用。
"""

from __future__ import annotations

import json
import os
import sys

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}
NUM_LABELS = 3
NEUTRAL_LABEL = 1  # NEUTRAL label index in LABEL_MAP


def check_dependencies() -> None:
    """检查训练所需的依赖是否安装，缺少则退出。"""
    print("=== Checking dependencies ===")
    try:
        import numpy as np

        print(f"  numpy: OK ({np.__version__})")
    except ImportError as e:
        print(f"  numpy: FAILED - {e}")
        sys.exit(1)

    try:
        import torch

        print(f"  torch: OK ({torch.__version__})")
    except ImportError as e:
        print(f"  torch: FAILED - {e}")
        sys.exit(1)

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        print("  transformers: OK")
    except ImportError as e:
        print(f"  transformers: FAILED - {e}")
        sys.exit(1)

    try:
        from datasets import Dataset  # noqa: F401

        print("  datasets: OK")
    except ImportError as e:
        print(f"  datasets: FAILED - {e}")
        sys.exit(1)

    try:
        from sklearn.metrics import (  # noqa: F401
            accuracy_score,
            f1_score,
            precision_score,
            recall_score,
        )

        print("  sklearn: OK")
    except ImportError as e:
        print(f"  sklearn: FAILED - {e}")
        sys.exit(1)

    print("=== All dependencies OK ===\n")


def check_peft_dependency() -> None:
    """额外检查 PEFT 依赖，LoRA 训练专用。"""
    try:
        import peft

        print(f"  peft: OK ({peft.__version__})")
    except ImportError as e:
        print(f"  peft: FAILED - {e}")
        print("  Install with: pip install peft>=0.14.0")
        sys.exit(1)


def load_dataset(file_path: str):
    """从 JSONL 文件加载数据集，每行包含 text 和 label 字段。"""
    print(f"Loading dataset: {file_path}")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    texts = []
    labels = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                texts.append(item["text"])
                labels.append(item["label"])

    from datasets import Dataset

    ds = Dataset.from_dict({"text": texts, "label": labels})
    print(f"  Loaded {len(ds)} samples")
    return ds


def compute_metrics(eval_pred):
    """计算分类指标：accuracy、macro F1/precision/recall。"""
    logits, labels = eval_pred
    predictions = logits.argmax(axis=-1)

    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

    return {
        "accuracy": accuracy_score(labels, predictions),
        "f1_macro": f1_score(labels, predictions, average="macro"),
        "precision_macro": precision_score(labels, predictions, average="macro"),
        "recall_macro": recall_score(labels, predictions, average="macro"),
    }


def oversample_minority(dataset, target_label=NEUTRAL_LABEL):
    """通过复制少数类样本来平衡类别分布。"""
    from datasets import Dataset

    items = dataset.to_dict()
    labels = items["label"]
    majority = {
        k: [v for i, v in enumerate(vs) if labels[i] != target_label] for k, vs in items.items()
    }
    minority = {
        k: [v for i, v in enumerate(vs) if labels[i] == target_label] for k, vs in items.items()
    }
    majority_count = len(majority["text"])
    minority_count = len(minority["text"])
    if minority_count == 0:
        return dataset
    dup_count = majority_count // minority_count
    remainder = majority_count % minority_count
    for k in minority:
        minority[k] = minority[k] * dup_count + minority[k][:remainder]
    merged = {k: majority[k] + minority[k] for k in items}
    print(
        f"  Oversampled label {target_label}: {minority_count} -> {majority_count}, "
        f"total samples: {len(merged['text'])}"
    )
    return Dataset.from_dict(merged)


class WeightedTrainer:
    """带类别加权交叉熵损失的 Trainer。

    NEUTRAL (label=1) 获得 2x 权重以缓解类别不平衡。
    """

    def __new__(cls, *args, **kwargs):
        import torch
        from transformers import Trainer

        class _WeightedTrainerImpl(Trainer):
            def compute_loss(self, model, inputs, return_outputs=False, **kw):
                labels = inputs.pop("labels")
                outputs = model(**inputs)
                logits = outputs.logits
                weight = torch.tensor(
                    [1.0, 2.0, 1.0],
                    device=logits.device,
                    dtype=logits.dtype,
                )
                loss_fct = torch.nn.CrossEntropyLoss(weight=weight)
                loss = loss_fct(logits, labels)
                return (loss, outputs) if return_outputs else loss

        return _WeightedTrainerImpl(*args, **kwargs)
