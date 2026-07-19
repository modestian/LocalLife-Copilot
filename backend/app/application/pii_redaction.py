"""PII scanning and redaction service for feedback dataset generation.

Implements the sensitive-information detection and masking rules defined in:
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §4.4:
  "correction 最大 4000 字，入库前执行敏感信息检测和脱敏标记"
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §9:
  "训练数据集不直接引用可变业务表，生成时固化、脱敏、哈希并记录来源许可"
- docs/project/大众点评AI智能助手-05-具体设计.md §9.2:
  "去除重复和近重复文本；脱敏手机号、地址细节、账号标识"
- docs/project/大众点评AI智能助手-05-具体设计.md §10:
  "输出：事实引用、敏感内容、个人信息和危险链接检查"

ST-501 acceptance criterion ④:
  手机号、身份证、邮箱等敏感信息在导出前完成脱敏，未授权样本不得进入数据集。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Redaction version (stored in datasets.redaction_version)
# ---------------------------------------------------------------------------

REDACTION_VERSION = "pii-v1.0"

# ---------------------------------------------------------------------------
# PII regex patterns (Chinese locale)
# ---------------------------------------------------------------------------

# Chinese mobile phone: 11 digits starting with 1[3-9]
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")

# Chinese ID card: 18 digits (last may be X), with basic checksum-friendly format
ID_CARD_PATTERN = re.compile(
    r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]"
)

# Email address
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Ordered patterns: longest/most-specific first to prevent substring overlap.
# ID card (18 chars) must be matched before phone (11 chars), otherwise
# the phone regex will match substrings inside ID card numbers.
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("id_card", ID_CARD_PATTERN),
    ("phone", PHONE_PATTERN),
    ("email", EMAIL_PATTERN),
]


# ---------------------------------------------------------------------------
# Scan result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PIIScanResult:
    """Result of scanning a text for PII.

    Attributes:
        original_text: The input text before redaction.
        redacted_text: The text after masking all detected PII.
        findings: Mapping of PII type → count of detections.
        pii_detected: True if any PII pattern matched.
    """

    original_text: str
    redacted_text: str
    findings: dict[str, int] = field(default_factory=dict)
    pii_detected: bool = False


# ---------------------------------------------------------------------------
# PII Scanner
# ---------------------------------------------------------------------------


class PIIScanner:
    """Detects Chinese phone numbers, ID card numbers and emails in text.

    Per §4.4: "correction 入库前执行敏感信息检测和脱敏标记".
    Per §9.2: "脱敏手机号、地址细节、账号标识".
    """

    def scan(self, text: str | None) -> PIIScanResult:
        """Scan *text* for PII and return findings without modifying it.

        Returns a :class:`PIIScanResult` with ``original_text == text``
        and ``redacted_text`` containing masked versions of any matches.
        """
        if text is None or not text:
            return PIIScanResult(
                original_text=text or "",
                redacted_text=text or "",
                findings={},
                pii_detected=False,
            )

        findings: dict[str, int] = {}
        redacted = text

        # Scan in order: longest pattern first to avoid substring overlap.
        for pii_type, pattern in PII_PATTERNS:
            # Scan against the current redacted text (after prior patterns masked).
            # This prevents shorter patterns from matching inside already-masked PII.
            matches = pattern.findall(redacted)
            count = len(matches)
            if count > 0:
                findings[pii_type] = count
                redacted = pattern.sub(self._mask_match, redacted)

        return PIIScanResult(
            original_text=text,
            redacted_text=redacted,
            findings=findings,
            pii_detected=bool(findings),
        )

    @staticmethod
    def _mask_match(match: re.Match[str]) -> str:
        """Mask a PII match, keeping first and last characters visible.

        Examples:
            13812345678 → 1***********8
            abc@example.com → a************m
        """
        value = match.group()
        if len(value) <= 2:
            return "*" * len(value)
        # Keep first char + last char, mask the rest
        masked = value[0] + "*" * (len(value) - 2) + value[-1]
        return masked


# ---------------------------------------------------------------------------
# Redaction service (applies scanning to feedback corrections)
# ---------------------------------------------------------------------------


class RedactionService:
    """Applies PII redaction to feedback text fields.

    Per §4.4: feedback.correction is scanned and masked before
    the feedback is eligible for dataset inclusion.
    Per §11.8: ``datasets.redaction_version`` records which rule
    version was applied during dataset generation.
    """

    def __init__(self, scanner: PIIScanner | None = None) -> None:
        self._scanner = scanner or PIIScanner()

    def redact(self, text: str | None) -> PIIScanResult:
        """Scan *text* for PII and return the redaction result.

        The returned ``redacted_text`` should be used as the
        canonical text in dataset export.  The ``findings`` dict
        feeds into the quality report's PII section.
        """
        return self._scanner.scan(text)

    @property
    def version(self) -> str:
        """Return the redaction rule version (stored in datasets.redaction_version)."""
        return REDACTION_VERSION

    def redact_batch(self, texts: list[str | None]) -> list[PIIScanResult]:
        """Redact a batch of texts (for dataset generation)."""
        return [self.redact(t) for t in texts]
