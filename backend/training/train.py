import argparse
import json
import os
import sys
import traceback

# Ensure Unicode output works on Windows GBK consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}
NUM_LABELS = 3
NEUTRAL_LABEL = 1  # NEUTRAL label index in LABEL_MAP


def check_dependencies():
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
        from datasets import Dataset

        print("  datasets: OK")
    except ImportError as e:
        print(f"  datasets: FAILED - {e}")
        sys.exit(1)

    try:
        from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

        print("  sklearn: OK")
    except ImportError as e:
        print(f"  sklearn: FAILED - {e}")
        sys.exit(1)

    print("=== All dependencies OK ===\n")


def load_dataset(file_path):
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
    """Oversample minority class by duplication to balance class distribution."""
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
    """Trainer with class-weighted cross-entropy loss.

    NEUTRAL (label=1) gets 2x weight to counteract class imbalance.
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
