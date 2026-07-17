"""Create knowledge base, document, version, and chunk metadata tables.

Revision ID: 20260717_0003
Revises: 20260716_0002
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260717_0003"
down_revision: str | None = "20260716_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )


def deleted_at_column() -> sa.Column:
    return sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True)


def version_column() -> sa.Column:
    return sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1")


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        uuid_column("id"),
        uuid_column("department_id", nullable=True),
        uuid_column("owner_id"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        uuid_column("embedding_model_version_id"),
        sa.Column(
            "chunk_size",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
            server_default="500",
        ),
        sa.Column(
            "chunk_overlap",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
            server_default="80",
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        version_column(),
        created_at_column(),
        updated_at_column(),
        deleted_at_column(),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_kb_department",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_kb_owner"),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_bases"),
        sa.UniqueConstraint("department_id", "normalized_name", "status", name="uq_kb_name_status"),
        sa.CheckConstraint("chunk_size BETWEEN 100 AND 4000", name=op.f("ck_kb_chunk_size")),
        sa.CheckConstraint("chunk_overlap < chunk_size", name=op.f("ck_kb_overlap")),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name=op.f("ck_kb_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_kb_department_status",
        "knowledge_bases",
        ["department_id", "status", "created_at"],
    )

    op.create_table(
        "documents",
        uuid_column("id"),
        uuid_column("knowledge_base_id"),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(500), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="UPLOADED"),
        sa.Column(
            "current_version_no",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        version_column(),
        created_at_column(),
        updated_at_column(),
        deleted_at_column(),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="fk_documents_kb",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "source_type",
            "source_key",
            name="uq_documents_source",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'UPLOADED', 'PARSING', 'INDEXING', 'READY', "
            "'FAILED', 'ARCHIVED', 'DELETED'"
            ")",
            name=op.f("ck_documents_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_documents_kb_status",
        "documents",
        ["knowledge_base_id", "status", "created_at"],
    )

    op.create_table(
        "document_versions",
        uuid_column("id"),
        uuid_column("document_id"),
        sa.Column("version_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("file_uri", sa.String(1000), nullable=False),
        sa.Column("file_sha256", sa.CHAR(64), nullable=False),
        sa.Column("file_size", mysql.BIGINT(unsigned=True), nullable=False),
        sa.Column("parser_name", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("cleaning_config_json", mysql.JSON(), nullable=False),
        sa.Column("splitter_config_json", mysql.JSON(), nullable=False),
        sa.Column(
            "is_current",
            mysql.TINYINT(display_width=1),
            nullable=False,
            server_default="1",
        ),
        created_at_column(),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_doc_versions_document",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_versions"),
        sa.UniqueConstraint("document_id", "version_no", name="uq_doc_version"),
        sa.CheckConstraint("version_no > 0", name=op.f("ck_doc_version_no")),
        sa.CheckConstraint("file_size > 0", name=op.f("ck_doc_version_file_size")),
        sa.CheckConstraint("is_current IN (0, 1)", name=op.f("ck_doc_version_is_current")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "chunks",
        uuid_column("id"),
        uuid_column("document_version_id"),
        sa.Column("chunk_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("token_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("page_number", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("metadata_json", mysql.JSON(), nullable=False),
        uuid_column("embedding_model_version_id"),
        sa.Column("opensearch_document_id", sa.String(191), nullable=False),
        sa.Column("index_status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("indexed_at", mysql.DATETIME(fsp=6), nullable=True),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["document_versions.id"],
            name="fk_chunks_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.UniqueConstraint("document_version_id", "chunk_no", name="uq_chunks_no"),
        sa.UniqueConstraint("opensearch_document_id", name="uq_chunks_os_id"),
        sa.CheckConstraint("token_count > 0", name=op.f("ck_chunks_token_count")),
        sa.CheckConstraint(
            "index_status IN ('PENDING', 'INDEXED', 'FAILED', 'DELETED')",
            name=op.f("ck_chunks_index_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_chunks_index_status", "chunks", ["index_status", "updated_at"])


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("knowledge_bases")
