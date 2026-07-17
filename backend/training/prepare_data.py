# 修改 prepare_data.py
import json
import random


def prepare_data(input_file, train_file, val_file, test_file):
    data = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                item = json.loads(line)
                data.append({"text": item["text"], "label": item["sentiment"]})

    label_map = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}
    for item in data:
        item["label"] = label_map[item["label"]]

    random.seed(42)
    random.shuffle(data)

    total = len(data)
    train_split = int(total * 0.7)
    val_split = int(total * 0.85)

    with open(train_file, "w", encoding="utf-8") as f:
        for item in data[:train_split]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(val_file, "w", encoding="utf-8") as f:
        for item in data[train_split:val_split]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(test_file, "w", encoding="utf-8") as f:
        for item in data[val_split:]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(
        f"Total: {total}, Train: {train_split}, Val: {val_split - train_split}, Test: {total - val_split}"
    )


if __name__ == "__main__":
    prepare_data(
        "backend/tests/data/training_data_1000.jsonl",
        "backend/training/data/train.jsonl",
        "backend/training/data/val.jsonl",
        "backend/training/data/test.jsonl",
    )
