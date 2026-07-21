"""全参数微调训练脚本（ST-401 遗留基线模型）。

共享函数已提取至 training.common 模块。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

# Ensure Unicode output works on Windows GBK consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from training.common import (
    LABEL_MAP,
    NUM_LABELS,
    WeightedTrainer,
    check_dependencies,
    compute_metrics,
    load_dataset,
    oversample_minority,
)


def main():
    print("=" * 60)
    print("Sentiment Classification Model Fine-tuning")
    print("=" * 60)

    check_dependencies()

    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", default="uer/roberta-base-finetuned-dianping-chinese")
    parser.add_argument("--train_file", default="backend/training/data/train.jsonl")
    parser.add_argument("--val_file", default="backend/training/data/val.jsonl")
    parser.add_argument("--test_file", default="backend/training/data/test.jsonl")
    parser.add_argument("--output_dir", default="backend/training/output")
    parser.add_argument("--num_train_epochs", type=int, default=8)
    parser.add_argument("--per_device_train_batch_size", type=int, default=8)
    parser.add_argument("--per_device_eval_batch_size", type=int, default=8)
    parser.add_argument("--learning_rate", type=float, default=1e-5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Arguments: {vars(args)}")
    print()

    print("=== Setting seed ===")
    from transformers import set_seed

    set_seed(args.seed)
    print(f"Seed: {args.seed}")

    print("\n=== Loading tokenizer ===")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    print(f"Tokenizer: {tokenizer.__class__.__name__}")

    print("\n=== Loading model ===")
    from transformers import AutoModelForSequenceClassification

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name,
        num_labels=NUM_LABELS,
        ignore_mismatched_sizes=True,
    )
    print(f"Model: {model.__class__.__name__}")
    print(f"Number of labels: {model.num_labels}")

    model.config.id2label = {v: k for k, v in LABEL_MAP.items()}
    model.config.label2id = LABEL_MAP

    def tokenize_function(examples):
        return tokenizer(
            examples["text"],
            padding="max_length",
            truncation=True,
            max_length=128,
        )

    print("\n=== Loading datasets ===")
    train_dataset = load_dataset(args.train_file)
    print("  Oversampling NEUTRAL class in training data...")
    train_dataset = oversample_minority(train_dataset).map(tokenize_function, batched=True)
    val_dataset = load_dataset(args.val_file).map(tokenize_function, batched=True)
    test_dataset = load_dataset(args.test_file).map(tokenize_function, batched=True)

    print("\n=== Configuring training ===")
    from transformers import EarlyStoppingCallback, TrainingArguments

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.num_train_epochs,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        learning_rate=args.learning_rate,
        warmup_steps=100,
        weight_decay=0.01,
        logging_dir=f"{args.output_dir}/logs",
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",
        greater_is_better=True,
        seed=args.seed,
        fp16=False,
        report_to="none",
    )

    trainer = WeightedTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )

    print("\n=== Starting training ===")
    trainer.train()

    print("\n=== Evaluating on test set ===")
    test_results = trainer.evaluate(test_dataset)
    print(f"Test results: {test_results}")

    print("\n=== Saving model ===")
    os.makedirs(f"{args.output_dir}/final_model", exist_ok=True)
    model.save_pretrained(f"{args.output_dir}/final_model")
    tokenizer.save_pretrained(f"{args.output_dir}/final_model")
    print(f"Model saved to {args.output_dir}/final_model")

    print("\n" + "=" * 60)
    print("Training completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
