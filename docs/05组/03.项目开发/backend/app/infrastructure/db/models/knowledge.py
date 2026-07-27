from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary, utc_now
from app.infrastructure.db.models.identity import (
    DATETIME_6,
    MYSQL_TABLE_OPTIONS,
    UNSIGNED_INTEGER,
    TimestampMixin,
    VersionMixin,
)

UNSIGNED_BIGINT = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")
UNSIGNED_SMALLINT = SmallInteger().with_variant(mysql.SMALLINT(unsigned=True), "mysql")
MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
JSON_TYPE = JSON().with_variant(mysql.JSON(), "mysql")


class KnowledgeBase(TimestampMixin, VersionMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "normalized_name",
            "active_flag",
            name="uq_kb_tenant_name_active",
        ),
        CheckConstraint("chunk_size BETWEEN 100 AND 4000", name="chunk_size"),
        CheckConstraint("chunk_overlap < chunk_size", name="overlap"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED', 'DELETED')", name="status"),
        Index("ix_kb_department_status", "department_id", "status", "created_at"),
        Index("ix_kb_tenant_status", "tenant_id", "status", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    tenant_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("departments.id", name="fk_kb_tenant", ondelete="RESTRICT"),
        nullable=False,
    )
    department_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("departments.id", name="fk_kb_department", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_kb_owner"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model_version_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    chunk_size: Mapped[int] = mapped_column(
        UNSIGNED_SMALLINT, nullable=False, default=500, server_default="500"
    )
    chunk_overlap: Mapped[int] = mapped_column(
        UNSIGNED_SMALLINT, nullable=False, default=80, server_default="80"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    active_flag: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed("CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END", persisted=True),
        nullable=True,
    )


class Document(TimestampMixin, VersionMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "source_type",
            "source_key",
            name="uq_documents_source",
        ),
        CheckConstraint(
            "status IN ('UPLOADED', 'PARSING', 'INDEXING', 'READY', "
            "'FAILED', 'ARCHIVED', 'DELETED')",
            name="status",
        ),
        Index("ix_documents_kb_status", "knowledge_base_id", "status", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("knowledge_bases.id", name="fk_documents_kb"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="UPLOADED", server_default="UPLOADED"
    )
    current_version_no: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER, nullable=False, default=0, server_default="0"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_doc_version"),
        CheckConstraint("version_no > 0", name="version_no"),
        CheckConstraint("file_size > 0", name="file_size"),
        CheckConstraint("is_current IN (0, 1)", name="is_current"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    document_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("documents.id", name="fk_doc_versions_document"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    file_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    file_size: Mapped[int] = mapped_column(UNSIGNED_BIGINT, nullable=False)
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    cleaning_config_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    splitter_config_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class Chunk(TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_no", name="uq_chunks_no"),
        UniqueConstraint("opensearch_document_id", name="uq_chunks_os_id"),
        CheckConstraint("token_count > 0", name="token_count"),
        CheckConstraint(
            "index_status IN ('PENDING', 'INDEXED', 'FAILED', 'DELETED')",
            name="index_status",
        ),
        Index("ix_chunks_index_status", "index_status", "updated_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    document_version_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("document_versions.id", name="fk_chunks_version"),
        nullable=False,
    )
    chunk_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    content: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    token_count: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    page_number: Mapped[int | None] = mapped_column(UNSIGNED_INTEGER, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    embedding_model_version_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    opensearch_document_id: Mapped[str] = mapped_column(String(191), nullable=False)
    index_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True
    )
