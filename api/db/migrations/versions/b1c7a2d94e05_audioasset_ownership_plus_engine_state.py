"""audioasset ownership + engine state table

Revision ID: b1c7a2d94e05
Revises: 466e02b2506a
Create Date: 2026-11-22

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = 'b1c7a2d94e05'
down_revision: str | None = '466e02b2506a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # ownership for studio-preview assets (message_id is NULL there).
    # Defensive: dev boots run create_all first, which may already have created
    # tables with the new columns.
    if "audioasset" in tables:
        cols = {c["name"] for c in inspector.get_columns("audioasset")}
        if "user_id" not in cols:
            with op.batch_alter_table('audioasset', schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
                )
                batch_op.create_index(batch_op.f('ix_audioasset_user_id'), ['user_id'], unique=False)
                batch_op.create_foreign_key(
                    'fk_audioasset_user_id_user', 'user', ['user_id'], ['id']
                )

    # persisted admin engine enable/disable (FR-9)
    if 'enginestate' not in tables:
        op.create_table('enginestate',
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('name')
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'enginestate' in inspector.get_table_names():
        op.drop_table('enginestate')
    cols = {c["name"] for c in inspector.get_columns("audioasset")}
    if 'user_id' in cols:
        with op.batch_alter_table('audioasset', schema=None) as batch_op:
            batch_op.drop_constraint('fk_audioasset_user_id_user', type_='foreignkey')
            batch_op.drop_index(batch_op.f('ix_audioasset_user_id'))
            batch_op.drop_column('user_id')
