"""add image_url to news

Revision ID: a1b2c3d4e5f6
Revises: 0dc324f654ef
Create Date: 2026-02-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '0dc324f654ef'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('news', schema=None) as batch_op:
        batch_op.add_column(sa.Column('image_url', sa.String(length=1000), nullable=True))


def downgrade():
    with op.batch_alter_table('news', schema=None) as batch_op:
        batch_op.drop_column('image_url')
