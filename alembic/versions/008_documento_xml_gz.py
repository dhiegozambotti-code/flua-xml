"""008: XML completo (gzip) persistido no Postgres.

Storage local da Railway é efêmero; guardar o XML no banco garante
persistência entre redeploys e permite o ERP rebaixar o XML depois.

Revision ID: 008
Revises: 007
Create Date: 2026-06-18
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documento", sa.Column("xml_gz", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("documento", "xml_gz")
