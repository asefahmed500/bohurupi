"""customer support, MCP knowledge base and voice-training tables

Revision ID: b2c8d4e6f9a1
Revises: b1c7a2d94e05

Safe/idempotent: dev boots run create_all first, so tables/columns may already
exist. Never drops or rewrites data.
"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b2c8d4e6f9a1"
down_revision: str | None = "b1c7a2d94e05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STRING = sqlmodel.sql.sqltypes.AutoString
JSON = sa.JSON()


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _tables()

    if "business" not in existing:
        op.create_table(
            "business",
            sa.Column("id", STRING, nullable=False),
            sa.Column("name", STRING, nullable=False),
            sa.Column("slug", STRING, nullable=False),
            sa.Column("system_prompt", STRING, nullable=False),
            sa.Column("languages", JSON, nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("business", schema=None) as b:
            b.create_index(b.f("ix_business_slug"), ["slug"], unique=True)

    if "knowledgedocument" not in existing:
        op.create_table(
            "knowledgedocument",
            sa.Column("id", STRING, nullable=False),
            sa.Column("business_id", STRING, nullable=False),
            sa.Column("title", STRING, nullable=False),
            sa.Column("source", STRING, nullable=False),
            sa.Column("content", STRING, nullable=False),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("knowledgedocument", schema=None) as b:
            b.create_index(b.f("ix_knowledgedocument_business_id"), ["business_id"])

    if "knowledgechunk" not in existing:
        op.create_table(
            "knowledgechunk",
            sa.Column("id", STRING, nullable=False),
            sa.Column("document_id", STRING, nullable=False),
            sa.Column("business_id", STRING, nullable=False),
            sa.Column("text", STRING, nullable=False),
            sa.Column("embedding", JSON, nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["knowledgedocument.id"]),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for col in ("document_id", "business_id"):
            with op.batch_alter_table("knowledgechunk", schema=None) as b:
                b.create_index(b.f(f"ix_knowledgechunk_{col}"), [col])

    if "supportticket" not in existing:
        op.create_table(
            "supportticket",
            sa.Column("id", STRING, nullable=False),
            sa.Column("business_id", STRING, nullable=False),
            sa.Column("conversation_id", STRING, nullable=True),
            sa.Column("customer_email", STRING, nullable=False),
            sa.Column("subject", STRING, nullable=False),
            sa.Column("message", STRING, nullable=False),
            sa.Column("status", STRING, nullable=False),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        for col in ("business_id", "conversation_id"):
            with op.batch_alter_table("supportticket", schema=None) as b:
                b.create_index(b.f(f"ix_supportticket_{col}"), [col])

    if "voicetrainingjob" not in existing:
        op.create_table(
            "voicetrainingjob",
            sa.Column("id", STRING, nullable=False),
            sa.Column("voice_id", STRING, nullable=False),
            sa.Column("status", STRING, nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("profile_path", STRING, nullable=True),
            sa.Column("features", JSON, nullable=True),
            sa.Column("error", STRING, nullable=True),
            sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
            sa.Column("finished_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
            sa.ForeignKeyConstraint(["voice_id"], ["voice.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("voicetrainingjob", schema=None) as b:
            b.create_index(b.f("ix_voicetrainingjob_voice_id"), ["voice_id"])

    voice_cols = _columns("voice")
    if "profile_path" not in voice_cols:
        with op.batch_alter_table("voice", schema=None) as b:
            b.add_column(sa.Column("profile_path", STRING, nullable=True))
    if "profile_version" not in voice_cols:
        with op.batch_alter_table("voice", schema=None) as b:
            b.add_column(sa.Column("profile_version", sa.Integer(), nullable=False, server_default="0"))

    conv_cols = _columns("conversation")
    if "business_id" not in conv_cols:
        with op.batch_alter_table("conversation", schema=None) as b:
            b.add_column(sa.Column("business_id", STRING, nullable=True))
            b.create_index(b.f("ix_conversation_business_id"), ["business_id"])
            b.create_foreign_key(
                "fk_conversation_business_id_business", "business", ["business_id"], ["id"]
            )


def downgrade() -> None:
    with op.batch_alter_table("conversation", schema=None) as b:
        b.drop_constraint("fk_conversation_business_id_business", type_="foreignkey")
        b.drop_index("ix_conversation_business_id")
        b.drop_column("business_id")
    with op.batch_alter_table("voice", schema=None) as b:
        b.drop_column("profile_version")
        b.drop_column("profile_path")
    for name in (
        "voicetrainingjob",
        "supportticket",
        "knowledgechunk",
        "knowledgedocument",
        "business",
    ):
        if name in _tables():
            op.drop_table(name)
