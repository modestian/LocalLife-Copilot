"""Create deterministic, text-disjoint sentiment training splits."""

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}
BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_unique_samples(input_file: Path) -> dict[str, list[dict[str, str | int]]]:
    """Deduplicate exact texts and reject contradictory labels."""
    labels_by_text: dict[str, str] = {}
    grouped: dict[str, list[dict[str, str | int]]] = defaultdict(list)
    for line in input_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        text = item["text"].strip()
        sentiment = item["sentiment"]
        previous = labels_by_text.setdefault(text, sentiment)
        if previous != sentiment:
            raise ValueError(f"Conflicting labels for duplicate text: {text!r}")

    for text, sentiment in labels_by_text.items():
        grouped[sentiment].append({"text": text, "label": LABEL_MAP[sentiment]})
    return grouped


def split_samples(
    grouped: dict[str, list[dict[str, str | int]]], seed: int
) -> tuple[list[dict], list[dict], list[dict]]:
    """Stratify by label while keeping each unique text in exactly one split."""
    rng = random.Random(seed)
    train: list[dict] = []
    validation: list[dict] = []
    test: list[dict] = []
    for sentiment in LABEL_MAP:
        samples = grouped[sentiment]
        rng.shuffle(samples)
        train_end = int(len(samples) * 0.7)
        validation_end = int(len(samples) * 0.85)
        train.extend(samples[:train_end])
        validation.extend(samples[train_end:validation_end])
        test.extend(samples[validation_end:])
    for split in (train, validation, test):
        rng.shuffle(split)
    return train, validation, test


def write_jsonl(path: Path, samples: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for item in samples:
            output.write(json.dumps(item, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=BACKEND_DIR / "tests" / "data" / "training_data_1000.jsonl",
    )
    parser.add_argument("--output-dir", type=Path, default=BACKEND_DIR / "training" / "data")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    splits = split_samples(load_unique_samples(args.input), args.seed)
    for filename, samples in zip(("train.jsonl", "val.jsonl", "test.jsonl"), splits, strict=True):
        write_jsonl(args.output_dir / filename, samples)
    print(f"Train: {len(splits[0])}, validation: {len(splits[1])}, test: {len(splits[2])}")


if __name__ == "__main__":
    main()
