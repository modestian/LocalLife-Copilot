# TK-202-06 runbook

OpenSearch 3.x stores the frozen dataset checksum in mapping `_meta`. Run from the repository root:

```powershell
Push-Location backend
python evaluation/run_search_evaluation.py --prepare-index
Pop-Location
```

The isolated `local-life-search-eval-v1` index does not change application aliases. Reports are
written to `backend/evaluation/reports/` in JSON and Markdown formats.
