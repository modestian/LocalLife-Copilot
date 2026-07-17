"""Manual smoke check for the configured sentiment model.

Run from ``backend`` with: ``python scripts/smoke_sentiment.py``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics import SentimentAnalyzer  # noqa: E402


def main() -> None:
    analyzer = SentimentAnalyzer()
    texts = [
        "????????????????",
        "??????????",
        "???????",
    ]
    for text, result in zip(texts, analyzer.analyze_batch(texts), strict=True):
        print(text)
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
