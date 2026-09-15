"""Store the figures a run found alongside its sources.

Images come from the pages being cited, so they belong with the rest of the
run's evidence rather than being re-fetched when a report is reopened.
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_sessions", sa.Column("images", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("research_sessions", "images")
