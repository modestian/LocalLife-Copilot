# Offline evaluation

`evaluate_sentiment.py` is the TK-401-06 offline evaluation entry point. By default it uses the
frozen `tests/data/benchmark_reviews.jsonl` benchmark from TK-401-02.

Run from the repository root after placing the approved model artifact:

```powershell
python backend/evaluation/evaluate_sentiment.py
```

Console output alone is not an acceptance artifact. The model owner still needs to commit an
evaluation report containing the model revision/artifact checksum, dataset checksum, Macro-F1,
confusion matrix, and reviewed boundary cases.
