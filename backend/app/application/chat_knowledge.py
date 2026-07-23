"""Resolve the shared public knowledge scope used by authenticated chat users."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.agents.contracts import RetrievalScope


class SharedChatKnowledgeUnavailable(RuntimeError):
    """The public chat corpus is missing or has an invalid tenant layout."""


class SharedChatKnowledgeDenied(PermissionError):
    """The request tried to select a knowledge base outside the public corpus."""


@dataclass(frozen=True, slots=True)
class PublicKnowledgeBase:
    id: UUID
    tenant_id: UUID


class SharedChatKnowledgeScopeResolver(Protocol):
    async def resolve(self, requested_ids: Sequence[UUID]) -> RetrievalScope: ...


def build_shared_chat_scope(
    rows: Iterable[PublicKnowledgeBase],
    requested_ids: Sequence[UUID],
) -> RetrievalScope:
    """Build one server-trusted scope from knowledge bases marked public.

    A READ grant to the system USER role marks a knowledge base as part of the
    public chat corpus. That corpus is shared by every authenticated account;
    user identity remains relevant only to conversation/message ownership.
    """
    public_rows = {row.id: row for row in rows}
    requested = frozenset(requested_ids)
    if requested and not requested.issubset(public_rows):
        raise SharedChatKnowledgeDenied("knowledge base is outside the public chat corpus")

    selected_ids = requested or frozenset(public_rows)
    if not selected_ids:
        raise SharedChatKnowledgeUnavailable("the public chat corpus is empty")

    tenant_ids = {public_rows[knowledge_base_id].tenant_id for knowledge_base_id in selected_ids}
    if len(tenant_ids) != 1:
        raise SharedChatKnowledgeUnavailable(
            "the public chat corpus must belong to exactly one tenant"
        )

    knowledge_base_ids = frozenset(str(value) for value in selected_ids)
    return RetrievalScope(
        tenant_id=str(next(iter(tenant_ids))),
        knowledge_base_ids=knowledge_base_ids,
        resource_scopes=frozenset(
            f"KNOWLEDGE_BASE:{knowledge_base_id}" for knowledge_base_id in knowledge_base_ids
        ),
    )
