# Sentiment model workflow

Model weights and checkpoints are build artifacts. They are intentionally excluded from Git;
source code, frozen data, configuration, metrics, and the artifact location/checksum belong in Git.

The current repository does **not** contain the trained TK-401-03 three-class model. Until its
owner publishes the artifact URI and SHA-256, the training result cannot be reproduced byte for
byte and the `Macro-F1 >= 0.80` acceptance criterion cannot be verified.

## Local workflow

Run commands from the repository root:

```powershell
python -m pip install -e ".\backend[training,dev]"
python backend/training/prepare_data.py
python backend/training/train.py
python backend/evaluation/evaluate_sentiment.py
Set-Location backend
python scripts/smoke_sentiment.py
```

Training writes the deployable Transformers artifact to
`backend/training/output/final_model/`. This ignored directory should contain at least model
weights, `config.json`, tokenizer configuration, and tokenizer vocabulary files.

## Runtime delivery

Compose mounts `backend/training/output/final_model` read-only at `/models/sentiment` and sets
`SENTIMENT_MODEL=/models/sentiment`. For a shared environment, download and verify an approved
artifact into that directory before starting Compose.

Alternatively, set `SENTIMENT_MODEL` to a Hugging Face model ID and pin
`SENTIMENT_MODEL_REVISION` to an immutable commit hash. Do not use the unmodified fallback
two-class Dianping model as evidence that TK-401-03 passed three-class acceptance.

## Required handoff metadata

- base model ID and immutable revision;
- dataset path/version and SHA-256;
- seed and all training hyperparameters;
- artifact URI and SHA-256;
- label mapping (`NEGATIVE=0`, `NEUTRAL=1`, `POSITIVE=2`);
- Macro-F1, per-class metrics, confusion matrix, and error report.
