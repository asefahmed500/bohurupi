"""webhook automation tables

Revision ID: c3d9e7f1a2b4
Revises: b2c8d4e6f9a1
Idempotent (create_all may already have created these tables in dev).
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c3d9e7f1a2b4"
down_revision: str | None = "b2c8d4e6f9a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRING = sqlmodel.sql.sqltypes.AutoString


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "webhook" not in existing:
        op.create_table(
            "webhook",
            sa.Column("id", STRING, nullable=False),
            sa.Column("owner_id", STRING, nullable=False),
            sa.Column("url", STRING, nullable=False),
            sa.Column("events", sa.JSON(), nullable=True),
            sa.Column("secret", STRING, nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("webhook", schema=None) as b:
            b.create_index("ix_webhook_owner_id", ["owner_id"])
    if "webhookdelivery" not in existing:
        op.create_table(
            "webhookdelivery",
            sa.Column("id", STRING, nullable=False),
            sa.Column("webhook_id", STRING, nullable=False),
            sa.Column("event", STRING, nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=False),
            sa.Column("error", STRING, nullable=True),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.ForeignKeyConstraint(["webhook_id"], ["webhook.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("webhookdelivery", schema=None) as b:
            b.create_index("ix_webhookdelivery_webhook_id", ["webhook_id"])


def downgrade() -> None:
    if "webhookdelivery" in _tables():
        op.drop_table("webhookdelivery")
    if "webhook" in _tables():
        op.drop_table("webhook")
