"""Versioned sensitive-word rules and bidirectional content checks for TK-103-02."""

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ContentDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class SensitiveMatchType(StrEnum):
    CONTAINS = "CONTAINS"
    EXACT = "EXACT"


class SensitiveRuleScope(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    BOTH = "BOTH"


@dataclass(frozen=True, slots=True)
class SensitiveRuleRecord:
    id: UUID
    word: str
    normalized_word: str
    scope: SensitiveRuleScope
    match_type: SensitiveMatchType
    severity: str
    version_no: int
    enabled: bool

    def applies_to(self, direction: ContentDirection) -> bool:
        return self.enabled and self.scope in {SensitiveRuleScope.BOTH, direction.value}


@dataclass(frozen=True, slots=True)
class ContentCheckResult:
    allowed: bool
    direction: ContentDirection
    matched_rule_ids: tuple[UUID, ...]
    decision: str


class SensitiveRuleRepository(Protocol):
    async def create_rule(
        self,
        *,
        word: str,
        normalized_word: str,
        scope: SensitiveRuleScope,
        match_type: SensitiveMatchType,
        severity: str,
        created_by: UUID,
    ) -> SensitiveRuleRecord: ...

    async def list_rules(self, *, enabled_only: bool = False) -> list[SensitiveRuleRecord]: ...

    async def disable_rule(self, *, rule_id: UUID) -> SensitiveRuleRecord | None: ...

    async def append_rejection_audit(
        self,
        *,
        actor_id: UUID,
        direction: ContentDirection,
        request_id: str,
        conversation_id: UUID | None,
        content_sha256: str,
        content_length: int,
        matched_rule_ids: tuple[UUID, ...],
    ) -> None: ...


class ContentSafetyService:
    def __init__(self, repository: SensitiveRuleRepository) -> None:
        self._repository = repository

    async def create_rule(
        self,
        *,
        word: str,
        scope: SensitiveRuleScope,
        match_type: SensitiveMatchType,
        severity: str,
        created_by: UUID,
    ) -> SensitiveRuleRecord:
        normalized_word = normalize_sensitive_text(word)
        if not normalized_word:
            raise ValueError("sensitive word must not be blank")
        normalized_severity = severity.strip().upper()
        if normalized_severity not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("severity must be LOW, MEDIUM or HIGH")
        return await self._repository.create_rule(
            word=word.strip(),
            normalized_word=normalized_word,
            scope=scope,
            match_type=match_type,
            severity=normalized_severity,
            created_by=created_by,
        )

    async def list_rules(self, *, enabled_only: bool = False) -> list[SensitiveRuleRecord]:
        return await self._repository.list_rules(enabled_only=enabled_only)

    async def disable_rule(self, *, rule_id: UUID) -> SensitiveRuleRecord | None:
        return await self._repository.disable_rule(rule_id=rule_id)

    async def check(
        self,
        *,
        content: str,
        direction: ContentDirection,
        actor_id: UUID,
        request_id: str,
        conversation_id: UUID | None = None,
    ) -> ContentCheckResult:
        normalized_content = normalize_sensitive_text(content)
        rules = await self._repository.list_rules(enabled_only=True)
        matched = tuple(
            rule.id
            for rule in rules
            if rule.applies_to(direction) and _matches(rule, normalized_content)
        )
        if not matched:
            return ContentCheckResult(True, direction, (), "ALLOW")

        await self._repository.append_rejection_audit(
            actor_id=actor_id,
            direction=direction,
            request_id=request_id,
            conversation_id=conversation_id,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content_length=len(content),
            matched_rule_ids=matched,
        )
        decision = "BLOCK_INPUT" if direction is ContentDirection.INPUT else "STOP_OUTPUT"
        return ContentCheckResult(False, direction, matched, decision)


def normalize_sensitive_text(value: str) -> str:
    """Normalize compatibility forms, case and whitespace before matching."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _matches(rule: SensitiveRuleRecord, normalized_content: str) -> bool:
    if rule.match_type is SensitiveMatchType.EXACT:
        return normalized_content == rule.normalized_word
    return rule.normalized_word in normalized_content
