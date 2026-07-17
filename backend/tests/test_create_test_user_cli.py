from argparse import Namespace

import pytest

from app.cli.create_test_user import (
    ROLE_NAMES,
    _normalized_email,
    _normalized_role,
    _normalized_username,
    _parser,
)


def test_test_user_inputs_are_normalized() -> None:
    assert _normalized_username("  TestUser  ") == "testuser"
    assert _normalized_email("  TEST@Example.COM ") == "test@example.com"
    assert _normalized_email("  ") is None
    assert _normalized_role(" kb_admin ") == "KB_ADMIN"


@pytest.mark.parametrize(
    ("normalizer", "value"),
    [
        (_normalized_username, " "),
        (_normalized_username, "x" * 65),
        (_normalized_email, "not-an-email"),
        (_normalized_role, "ROOT"),
    ],
)
def test_test_user_inputs_reject_invalid_values(normalizer, value: str) -> None:
    with pytest.raises(ValueError):
        normalizer(value)


def test_cli_requires_username_and_defaults_to_user_role() -> None:
    args = _parser().parse_args(["--username", "frontend-test"])

    assert args == Namespace(
        username="frontend-test",
        display_name=None,
        email=None,
        role="USER",
    )
    assert args.role in ROLE_NAMES
