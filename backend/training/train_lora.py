"""LoRA / QLoRA 训练脚本。

具体设计 §9.3：框架 Transformers Trainer + PEFT，方法 LoRA，
显存受限时使用 QLoRA（4-bit NF4）。

用法:
    # 正式训练
    python -m training.train_lora --job-id lora-001

    # CPU smoke test
    python -m training.train_lora --job-id smoke-001 --smoke
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

# Ensure Unicode output works on Windows GBK consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from training.common import (
    LABEL_MAP,
    NEUTRAL_LABEL,
    NUM_LABELS,
    WeightedTrainer,
    check_dependencies,
    check_peft_dependency,
    compute_metrics,
    load_dataset,
    oversample_minority,
)
from training.lora_config import (
    DEFAULT_SEED,
    LoRAHyperparameters,
    SmokeTestConfig,
    TrainingConfig,
    ensure_artifact_dirs,
    get_artifact_dir,
)
from training.utils import (
    compute_dir_sha256,
    save_training_snapshot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LoRA / QLoRA fine-tuning for sentiment classification"
    )
    parser.add_argument("--job-id", required=True, help="训练任务唯一 ID")
    parser.add_argument(
        "--base-model",
        default="uer/roberta-base-finetuned-dianping-chinese",
        help="基础模型 ID（必须在白名单中）",
    )
    parser.add_argument("--train-file", default="backend/training/data/train.jsonl")
    parser.add_argument("--val-file", default="backend/training/data/val.jsonl")
    parser.add_argument("--test-file", default="backend/training/data/test.jsonl")
    parser.add_argument("--dataset-id", default="local-dataset-v1", help="数据集 ID")
    parser.add_argument("--method", default="LORA", choices=["LORA", "QLORA"], help="训练方法")

    # LoRA 超参（默认值来自具体设计 §9.3）
    parser.add_argument("--r", type=int, default=8, help="LoRA 秩")
    parser.add_argument("--lora-alpha", type=int, default=16, help="LoRA alpha")
    parser.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout")
    parser.add_argument("--learning-rate", type=float, default=2e-4, help="学习率")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=16, help="批大小")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="随机种子")

    # Smoke 模式
    parser.add_argument("--smoke", action="store_true", help="CPU smoke test 模式")
    parser.add_argument("--max-train-samples", type=int, default=10, help="smoke 模式训练样本上限")
    parser.add_argument("--max-eval-samples", type=int, default=5, help="smoke 模式评估样本上限")

    return parser.parse_args()


def build_training_config(args: argparse.Namespace) -> TrainingConfig:
    """从 CLI 参数构建 TrainingConfig，校验白名单和方法枚举。"""
    hp = LoRAHyperparameters(
        r=args.r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        batch_size=args.batch_size,
        seed=args.seed,
    )
    return TrainingConfig(
        task_type="sentiment_classification",
        base_model_id=args.base_model,
        dataset_id=args.dataset_id,
        method=args.method,
        hyperparameters=hp,
    )


def build_smoke_config(args: argparse.Namespace) -> SmokeTestConfig:
    """从 CLI 参数构建 SmokeTestConfig。"""
    return SmokeTestConfig(
        max_train_samples=args.max_train_samples,
        max_eval_samples=args.max_eval_samples,
        seed=args.seed,
    )


def truncate_dataset(dataset, max_samples: int):
    """截断数据集到指定样本数（smoke 模式用）。"""
    if len(dataset) <= max_samples:
        return dataset
    return dataset.select(range(max_samples))


def main():
    args = parse_args()

    print("=" * 60)
    if args.smoke:
        print("LoRA Smoke Test (CPU)")
    else:
        print("LoRA Fine-tuning")
    print("=" * 60)

    # 1. 检查依赖
    check_dependencies()
    check_peft_dependency()

    # 2. 构建配置
    training_config = build_training_config(args)
    smoke_config = build_smoke_config(args) if args.smoke else None

    hp = training_config.hyperparameters
    if args.smoke:
        effective_epochs = smoke_config.epochs
        effective_batch_size = smoke_config.batch_size
        effective_seed = smoke_config.seed
    else:
        effective_epochs = hp.epochs
        effective_batch_size = hp.batch_size
        effective_seed = hp.seed

    print(f"\nTraining Config: {training_config.model_dump()}")
    if smoke_config:
        print(f"Smoke Config: {smoke_config.model_dump()}")

    # 3. 设置随机种子
    print("\n=== Setting seed ===")
    from transformers import set_seed

    set_seed(effective_seed)
    print(f"Seed: {effective_seed}")

    # 4. 创建产物目录
    print("\n=== Creating artifact directories ===")
    artifact_dirs = ensure_artifact_dirs(args.job_id)
    print(f"Artifact root: {get_artifact_dir(args.job_id)}")
    for name, path in artifact_dirs.items():
        print(f"  {name}: {path}")

    # 5. 加载 Tokenizer
    print("\n=== Loading tokenizer ===")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    print(f"Tokenizer: {tokenizer.__class__.__name__}")

    # 6. 加载基础模型 + 应用 PEFT
    print("\n=== Loading base model ===")
    import torch
    from transformers import AutoModelForSequenceClassification

    model_kwargs = {
        "num_labels": NUM_LABELS,
        "ignore_mismatched_sizes": True,
    }

    if args.method == "QLORA":
        try:
            from transformers import BitsAndBytesConfig

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
            )
            model_kwargs["quantization_config"] = bnb_config
            print("  Using QLoRA (4-bit NF4 quantization)")
        except ImportError:
            print("  WARNING: bitsandbytes not installed, falling back to LoRA")
            args.method = "LORA"

    model = AutoModelForSequenceClassification.from_pretrained(args.base_model, **model_kwargs)
    model.config.id2label = {v: k for k, v in LABEL_MAP.items()}
    model.config.label2id = LABEL_MAP
    print(f"  Model: {model.__class__.__name__}")
    print(f"  Number of labels: {model.num_labels}")

    # 7. 应用 PEFT LoRA
    print("\n=== Applying PEFT LoRA ===")
    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=hp.r,
        lora_alpha=hp.lora_alpha,
        lora_dropout=hp.lora_dropout,
        target_modules=["query", "value"],
        task_type="SEQ_CLS",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 8. 加载和预处理数据集
    print("\n=== Loading datasets ===")
    train_dataset = load_dataset(args.train_file)
    print("  Oversampling NEUTRAL class in training data...")
    train_dataset = oversample_minority(train_dataset)

    if args.smoke:
        train_dataset = truncate_dataset(train_dataset, smoke_config.max_train_samples)
        print(f"  Smoke: truncated train to {len(train_dataset)} samples")

    val_dataset = load_dataset(args.val_file)
    test_dataset = load_dataset(args.test_file)

    if args.smoke:
        val_dataset = truncate_dataset(val_dataset, smoke_config.max_eval_samples)
        test_dataset = truncate_dataset(test_dataset, smoke_config.max_eval_samples)
        print(f"  Smoke: truncated val to {len(val_dataset)} samples")
        print(f"  Smoke: truncated test to {len(test_dataset)} samples")

    def tokenize_function(examples):
        return tokenizer(
            examples["text"],
            padding="max_length",
            truncation=True,
            max_length=128,
        )

    train_dataset = train_dataset.map(tokenize_function, batched=True)
    val_dataset = val_dataset.map(tokenize_function, batched=True)
    test_dataset = test_dataset.map(tokenize_function, batched=True)

    # 9. 配置训练参数
    print("\n=== Configuring training ===")
    from transformers import EarlyStoppingCallback, TrainingArguments

    checkpoint_dir = artifact_dirs["checkpoints"]
    log_dir = artifact_dirs["logs"]

    training_args = TrainingArguments(
        output_dir=str(checkpoint_dir),
        num_train_epochs=effective_epochs,
        per_device_train_batch_size=effective_batch_size,
        per_device_eval_batch_size=effective_batch_size,
        learning_rate=hp.learning_rate,
        warmup_steps=50,
        weight_decay=0.01,
        logging_dir=str(log_dir),
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        greater_is_better=True,
        seed=effective_seed,
        fp16=False,
        report_to="none",
    )

    # 10. 训练
    print("\n=== Starting training ===")
    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )
    trainer.train()

    # 11. 评估
    print("\n=== Evaluating on test set ===")
    test_results = trainer.evaluate(test_dataset)
    print(f"Test results: {test_results}")

    # 12. 保存 Adapter 和 Tokenizer
    print("\n=== Saving adapter and tokenizer ===")
    adapter_dir = artifact_dirs["adapter"]
    tokenizer_dir = artifact_dirs["tokenizer"]
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(tokenizer_dir))
    print(f"  Adapter saved to: {adapter_dir}")
    print(f"  Tokenizer saved to: {tokenizer_dir}")

    # 13. 保存训练配置快照
    print("\n=== Saving training snapshot ===")
    config_data = training_config.model_dump()
    config_data["hyperparameters"]["to_hash"] = hp.to_hash()
    config_data["method"] = args.method
    config_data["smoke_mode"] = args.smoke

    snapshot_path = save_training_snapshot(
        config_data=config_data,
        artifact_dirs=artifact_dirs,
        metrics={k: v for k, v in test_results.items() if not k.startswith("total_")},
        dataset_files={
            "train": args.train_file,
            "val": args.val_file,
            "test": args.test_file,
        },
    )
    print(f"  Snapshot saved to: {snapshot_path}")

    # 14. 计算 Adapter SHA-256
    print("\n=== Computing adapter SHA-256 ===")
    adapter_sha256 = compute_dir_sha256(adapter_dir)
    print(f"  Adapter SHA-256: {adapter_sha256}")

    # 将哈希写入快照
    with snapshot_path.open("r", encoding="utf-8") as f:
        snapshot = json.load(f)
    snapshot["adapter_sha256"] = adapter_sha256
    with snapshot_path.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    # 15. 打印总结
    print("\n" + "=" * 60)
    print("LoRA training completed successfully!")
    print("=" * 60)
    print(f"  Job ID:          {args.job_id}")
    print(f"  Method:          {args.method}")
    print(f"  Base model:      {args.base_model}")
    print(f"  Adapter dir:     {adapter_dir}")
    print(f"  Adapter SHA-256: {adapter_sha256}")
    print(f"  Snapshot:        {snapshot_path}")
    print(f"  Test F1 (macro): {test_results.get('eval_f1_macro', 'N/A')}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
