import io
import json
from unittest.mock import MagicMock

import pytest

from app.agents.contracts import ModelInput
from app.agents.transformers_model import TransformersModelAdapter


def _json_response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def test_sentiment_classifier_label_forces_rule_based_routing(monkeypatch) -> None:
    urlopen = MagicMock(
        return_value=_json_response(
            {
                "model": "local-bert-classifier",
                "predicted_label": "POSITIVE",
                "scores": {"NEGATIVE": 0.1, "NEUTRAL": 0.2, "POSITIVE": 0.7},
            }
        )
    )
    monkeypatch.setattr("app.agents.transformers_model.urllib.request.urlopen", urlopen)
    adapter = TransformersModelAdapter(bailian_api_key="test-key")

    prediction = adapter.predict((ModelInput(task="route_intent", prompt="推荐川菜"),))[0]

    assert prediction.structured == {"intent": "general_chat", "confidence": 0.0}


def test_constraint_extraction_uses_empty_patch_without_classifier_call(monkeypatch) -> None:
    urlopen = MagicMock()
    monkeypatch.setattr("app.agents.transformers_model.urllib.request.urlopen", urlopen)
    adapter = TransformersModelAdapter(bailian_api_key="test-key")

    prediction = adapter.predict(
        (ModelInput(task="extract_constraints", prompt="人均 100 元以内"),)
    )[0]

    assert prediction.structured == {}
    urlopen.assert_not_called()


def test_bailian_request_requires_api_key() -> None:
    adapter = TransformersModelAdapter(bailian_api_key="")

    with pytest.raises(RuntimeError, match="BAILIAN_API_KEY"):
        adapter._call_bailian("rag_recommendation", "prompt")


def test_bailian_request_enables_json_response_format(monkeypatch) -> None:
    captured: dict = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _json_response({"choices": [{"message": {"content": '{"answer":"ok"}'}}]})

    monkeypatch.setattr("app.agents.transformers_model.urllib.request.urlopen", fake_urlopen)
    adapter = TransformersModelAdapter(bailian_api_key="test-key", bailian_timeout=3.0)

    text = adapter._call_bailian("rag_grounded_answer", "prompt")

    assert text == '{"answer":"ok"}'
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["timeout"] == 3.0
