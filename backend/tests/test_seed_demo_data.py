import json
from uuid import UUID

import pytest

from app.cli.seed_demo_data import (
    DEMO_QUESTIONS,
    DEMO_USERS,
    QUESTION_SET_PATH,
    _parser,
    _password_from_environment,
    _review_rows,
)


def test_demo_seed_fixture_has_stable_core_coverage() -> None:
    reviews = _review_rows()

    assert [user.username for user in DEMO_USERS] == ["demo-admin", "demo-user", "demo-merchant"]
    assert len(reviews) == 12
    assert {row["sentiment"] for row in reviews} == {"POSITIVE", "NEUTRAL", "NEGATIVE"}
    assert len({row["merchant_id"] for row in reviews}) == 2
    assert all(UUID(str(row["id"])) for row in reviews)
    assert DEMO_QUESTIONS[-1]["expected_fallback"] is True


def test_question_file_matches_the_seeded_question_set() -> None:
    payload = json.loads(QUESTION_SET_PATH.read_text(encoding="utf-8"))

    assert payload["suite"] == "st-702-demo-questions-v1"
    assert payload["questions"] == list(DEMO_QUESTIONS)


def test_demo_seed_password_is_read_from_a_named_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ST_702_TEST_PASSWORD", "local-only-password")

    assert _password_from_environment("ST_702_TEST_PASSWORD") == "local-only-password"
    assert _parser().parse_args([]).password_env == "DEMO_SEED_PASSWORD"


def test_demo_seed_rejects_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ST_702_MISSING_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="ST_702_MISSING_PASSWORD"):
        _password_from_environment("ST_702_MISSING_PASSWORD")
