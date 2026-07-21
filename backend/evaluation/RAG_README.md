# Grounded RAG evaluation (TK-301-06)

`rag_benchmark_v1.json` is the frozen, privacy-safe benchmark for multi-turn constraint retention,
citation correctness, hallucination rejection, and no-result fallback. It contains five cases per
category and directly executes the production routing, constraint extraction, grounded generation,
and citation-verification code without network dependencies.

Run from the repository root:

```powershell
Push-Location backend
python evaluation/evaluate_rag.py
Pop-Location
```

JSON and Markdown reports are written under `backend/evaluation/reports/` with the dataset version
and SHA-256 checksum. Citation correctness is gated at 0.95; no-result fallback, multi-turn context,
and hallucination rejection are independently gated at 0.90. A non-passing gate makes the command
exit with status 1.

## Annotation rules

- Multi-turn cases record all expected final constraints and the expected route after every turn.
- Citation cases require the accepted evidence IDs, stable source locations, and exact snapshots.
- Hallucination cases freeze deliberately unsupported outputs and their expected rejection reason.
- No-result cases cover empty, low-score, and insufficient-count evidence.

To change an annotation, create a new `dataset_version` instead of silently replacing the accepted
baseline. Review the JSON diff and report checksum together.
