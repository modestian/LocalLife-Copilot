from datetime import datetime

from app.core.ids import uuid7
from app.infrastructure.db.models.conversations import Message
from app.infrastructure.db.repositories.conversations import (
    _settings_after_truncate,
    _visible_branch_rows,
)


def row(sequence_no: int, *, parent=None) -> Message:
    return Message(
        id=uuid7(),
        conversation_id=CONVERSATION_ID,
        parent_message_id=parent,
        sequence_no=sequence_no,
        request_id=None,
        role="USER",
        content=f"message-{sequence_no}",
        status="COMPLETED",
        model_version_id=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=None,
        error_code=None,
        created_at=datetime(2026, 7, 21),
    )


CONVERSATION_ID = uuid7()


def test_visible_branch_excludes_messages_abandoned_after_truncate() -> None:
    first = row(1)
    second = row(2, parent=first.id)
    abandoned = row(3, parent=second.id)
    replacement = row(4, parent=second.id)

    visible = _visible_branch_rows([first, second, abandoned, replacement], replacement.id)

    assert [item.id for item in visible] == [first.id, second.id, replacement.id]


def test_legacy_parentless_history_uses_sequence_compatibility() -> None:
    first = row(1)
    second = row(2)
    third = row(3)

    visible = _visible_branch_rows([first, second, third], second.id)

    assert [item.id for item in visible] == [first.id, second.id]


def test_truncate_clears_derived_summary_and_constraints() -> None:
    settings = {
        "temperature": 0.2,
        "_memory_summary": {"text": "future facts"},
        "constraints": {"cuisines": ["川菜"]},
    }

    result = _settings_after_truncate(settings)

    assert result == {"temperature": 0.2}
