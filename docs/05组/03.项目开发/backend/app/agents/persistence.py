"""Persistence boundary for verified grounded assistant responses."""

from uuid import UUID

from app.agents.generation import GroundedGeneration
from app.application.conversations import (
    ConversationRepository,
    MessageInput,
    MessageRole,
    MessageStatus,
    MessageView,
    SourceInput,
)


class GroundedPersistenceError(ValueError):
    """A verified source cannot be represented by the durable source schema."""


class GroundedResponsePersister:
    """Append an answer and its immutable source snapshots in one repository transaction."""

    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    async def persist(
        self,
        conversation_id: UUID,
        owner_user_id: UUID,
        generation: GroundedGeneration,
        *,
        request_id: str | None = None,
        parent_message_id: UUID | None = None,
        model_version_id: UUID | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> MessageView:
        sources = tuple(_source_input(source) for source in generation.sources)
        if generation.is_fallback and sources:
            raise GroundedPersistenceError("fallback responses must not persist sources")
        if not generation.is_fallback and not sources:
            raise GroundedPersistenceError("grounded responses must persist at least one source")
        return await self._repository.append_message(
            conversation_id,
            owner_user_id,
            MessageInput(
                role=MessageRole.ASSISTANT,
                content=generation.answer,
                status=MessageStatus.COMPLETED,
                parent_message_id=parent_message_id,
                request_id=request_id,
                model_version_id=model_version_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                sources=sources,
            ),
        )


def _source_input(source) -> SourceInput:
    try:
        chunk_id = UUID(source.chunk_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise GroundedPersistenceError("citation chunk_id must be a UUID") from exc
    return SourceInput(
        chunk_id=chunk_id,
        rank_no=source.rank_no,
        source_location_snapshot=source.source_location,
        content_snapshot=source.content_snapshot,
        score=source.score,
    )
