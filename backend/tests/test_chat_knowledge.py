from uuid import UUID

import pytest

from app.application.chat_knowledge import (
    PublicKnowledgeBase,
    SharedChatKnowledgeDenied,
    SharedChatKnowledgeUnavailable,
    build_shared_chat_scope,
)

TENANT_ID = UUID("70200000-0000-4000-8000-000000000001")
KB_ONE = UUID("70200000-0000-4000-8000-000000000010")
KB_TWO = UUID("70200000-0000-4000-8000-000000000011")


def public_rows() -> list[PublicKnowledgeBase]:
    return [
        PublicKnowledgeBase(KB_ONE, TENANT_ID),
        PublicKnowledgeBase(KB_TWO, TENANT_ID),
    ]


def test_all_authenticated_chat_users_share_the_complete_public_corpus_by_default() -> None:
    scope = build_shared_chat_scope(public_rows(), [])

    assert scope.tenant_id == str(TENANT_ID)
    assert scope.knowledge_base_ids == frozenset({str(KB_ONE), str(KB_TWO)})
    assert scope.resource_scopes == frozenset(
        {f"KNOWLEDGE_BASE:{KB_ONE}", f"KNOWLEDGE_BASE:{KB_TWO}"}
    )


def test_client_can_only_narrow_within_the_public_corpus() -> None:
    scope = build_shared_chat_scope(public_rows(), [KB_TWO])
    assert scope.knowledge_base_ids == frozenset({str(KB_TWO)})

    with pytest.raises(SharedChatKnowledgeDenied):
        build_shared_chat_scope(public_rows(), [UUID(int=99)])


def test_public_corpus_must_exist_inside_one_server_trusted_tenant() -> None:
    with pytest.raises(SharedChatKnowledgeUnavailable, match="empty"):
        build_shared_chat_scope([], [])

    with pytest.raises(SharedChatKnowledgeUnavailable, match="exactly one tenant"):
        build_shared_chat_scope(
            [
                PublicKnowledgeBase(KB_ONE, TENANT_ID),
                PublicKnowledgeBase(KB_TWO, UUID(int=2)),
            ],
            [],
        )
