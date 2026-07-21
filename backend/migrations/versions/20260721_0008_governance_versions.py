"""Create prompt/model version and model deployment tables.

Revision ID: 20260721_0008
Revises: 20260720_0007
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260721_0008"
down_revision: str | None = "20260720_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def timestamp_column(name: str, *, update: bool = False) -> sa.Column:
    default = "CURRENT_TIMESTAMP(6)"
    if update:
        default += " ON UPDATE CURRENT_TIMESTAMP(6)"
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text(default))


def upgrade() -> None:
    op.create_table(
        "prompt_definitions",
        uuid_column("id"),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("scene", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at", update=True),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_definitions"),
        sa.UniqueConstraint("code", name="uq_prompt_definitions_code"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "prompt_versions",
        uuid_column("id"),
        uuid_column("prompt_definition_id"),
        sa.Column("version_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("variables_json", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        uuid_column("created_by"),
        timestamp_column("created_at"),
        sa.Column("published_at", mysql.DATETIME(fsp=6), nullable=True),
        uuid_column("published_by", nullable=True),
        sa.Column("publication_action", sa.String(16), nullable=True),
        sa.Column("publication_result", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_versions"),
        sa.ForeignKeyConstraint(
            ["prompt_definition_id"],
            ["prompt_definitions.id"],
            name="fk_prompt_versions_definition",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_prompt_versions_creator"),
        sa.ForeignKeyConstraint(
            ["published_by"], ["users.id"], name="fk_prompt_versions_publisher"
        ),
        sa.UniqueConstraint(
            "prompt_definition_id", "version_no", name="uq_prompt_versions_definition_version"
        ),
        sa.CheckConstraint("version_no > 0", name="ck_prompt_versions_version_no"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')", name="ck_prompt_versions_status"
        ),
        sa.CheckConstraint(
            "publication_action IS NULL OR publication_action IN ('PUBLISH', 'ROLLBACK')",
            name="ck_prompt_versions_publication_action",
        ),
        sa.CheckConstraint(
            "publication_result IS NULL OR publication_result IN ('SUCCEEDED', 'FAILED')",
            name="ck_prompt_versions_publication_result",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_prompt_versions_definition_status",
        "prompt_versions",
        ["prompt_definition_id", "status"],
    )
    op.create_table(
        "model_definitions",
        uuid_column("id"),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        timestamp_column("created_at"),
        timestamp_column("updated_at", update=True),
        sa.PrimaryKeyConstraint("id", name="pk_model_definitions"),
        sa.UniqueConstraint("code", name="uq_model_definitions_code"),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "model_versions",
        uuid_column("id"),
        uuid_column("model_definition_id"),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("base_model_ref", sa.String(500), nullable=False),
        sa.Column("adapter_uri", sa.String(1000), nullable=False),
        sa.Column("artifact_sha256", sa.CHAR(64), nullable=False),
        sa.Column("dimension", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("labels_json", mysql.JSON(), nullable=True),
        sa.Column("metrics_json", mysql.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="REGISTERED"),
        uuid_column("created_by"),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_model_versions"),
        sa.ForeignKeyConstraint(
            ["model_definition_id"], ["model_definitions.id"], name="fk_model_versions_definition"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_model_versions_creator"),
        sa.UniqueConstraint(
            "model_definition_id", "version", name="uq_model_versions_definition_version"
        ),
        sa.CheckConstraint(
            "status IN ('REGISTERED', 'EVALUATED', 'APPROVED', 'REJECTED', 'ARCHIVED')",
            name="ck_model_versions_status",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_model_versions_definition_status", "model_versions", ["model_definition_id", "status"]
    )
    op.create_table(
        "model_deployments",
        uuid_column("id"),
        sa.Column("scene", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        uuid_column("model_version_id"),
        sa.Column("traffic_percent", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        uuid_column("deployed_by"),
        sa.Column("reason", sa.String(1000), nullable=False),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_model_deployments"),
        sa.ForeignKeyConstraint(
            ["model_version_id"], ["model_versions.id"], name="fk_model_deployments_version"
        ),
        sa.ForeignKeyConstraint(["deployed_by"], ["users.id"], name="fk_model_deployments_actor"),
        sa.CheckConstraint(
            "traffic_percent BETWEEN 1 AND 100", name="ck_model_deployments_traffic_percent"
        ),
        sa.CheckConstraint(
            "action IN ('CANARY', 'FULL', 'ROLLBACK')", name="ck_model_deployments_action"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'FAILED')", name="ck_model_deployments_status"
        ),
        sa.CheckConstraint("result IN ('SUCCEEDED', 'FAILED')", name="ck_model_deployments_result"),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_model_deployments_route_status", "model_deployments", ["scene", "environment", "status"]
    )


def downgrade() -> None:
    op.drop_table("model_deployments")
    op.drop_table("model_versions")
    op.drop_table("model_definitions")
    op.drop_table("prompt_versions")
    op.drop_table("prompt_definitions")
