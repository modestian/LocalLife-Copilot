from functools import lru_cache
from typing import Optional

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer, PreTrainedModel, PreTrainedTokenizer

from .config import get_review_analysis_config
from .models import BatchSentimentResult, SentimentResult


class SentimentClassifier:
    _model: Optional[PreTrainedModel] = None
    _tokenizer: Optional[PreTrainedTokenizer] = None
    _model_version: Optional[str] = None
    _label_mapping: Optional[dict[int, str]] = None

    def __init__(self) -> None:
        self.config = get_review_analysis_config()

    def _ensure_loaded(self) -> None:
        if self._model is None or self._tokenizer is None:
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.config.model_name_or_path
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.config.model_name_or_path
            )
            self._model = self._model.to(self.config.device)
            self._model.eval()
            self._model_version = self._model.config._name_or_path

            if hasattr(self._model.config, "id2label") and self._model.config.id2label:
                self._label_mapping = {k: v.upper() for k, v in self._model.config.id2label.items()}
            else:
                self._label_mapping = self.config.label_mapping

    @property
    def model_version(self) -> str:
        self._ensure_loaded()
        return self._model_version or self.config.model_name_or_path

    @property
    def label_mapping(self) -> dict[int, str]:
        self._ensure_loaded()
        return self._label_mapping or self.config.label_mapping

    def classify(self, text: str) -> SentimentResult:
        self._ensure_loaded()
        return self.classify_batch([text]).results[0]

    def classify_batch(self, texts: list[str]) -> BatchSentimentResult:
        self._ensure_loaded()

        if not texts:
            return BatchSentimentResult(
                results=[],
                model_version=self.model_version,
                total_count=0,
                processed_count=0,
            )

        results: list[SentimentResult] = []
        batch_size = self.config.batch_size

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            inputs = self._tokenizer(
                batch_texts,
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            ).to(self.config.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits
                probabilities = torch.nn.functional.softmax(logits, dim=1)
                predicted_ids = torch.argmax(probabilities, dim=1).tolist()
                confidence_scores = probabilities.max(dim=1).values.tolist()

            for idx, pred_id in enumerate(predicted_ids):
                sentiment = self.label_mapping.get(pred_id, "NEUTRAL")
                results.append(
                    SentimentResult(
                        sentiment=sentiment,
                        confidence=float(confidence_scores[idx]),
                        model_version=self.model_version,
                    )
                )

        return BatchSentimentResult(
            results=results,
            model_version=self.model_version,
            total_count=len(texts),
            processed_count=len(results),
        )

    def clear(self) -> None:
        self._model = None
        self._tokenizer = None
        self._model_version = None
        self._label_mapping = None


@lru_cache(maxsize=1)
def get_classifier() -> SentimentClassifier:
    return SentimentClassifier()
