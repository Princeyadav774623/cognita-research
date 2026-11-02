"""Research jobs and their progress events.

Research moves out of the WebSocket handler and onto a queue a separate worker
drains, so a deploy or a dropped connection no longer kills a run in progress.
See jobs.py.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leased_by", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_jobs_user_id", "research_jobs", ["user_id"])
    op.create_index("ix_research_jobs_claimable", "research_jobs", ["state", "run_after"])

    op.create_table(
        "research_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(),
                  sa.ForeignKey("research_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_events_job_id_id", "research_events", ["job_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_research_events_job_id_id", table_name="research_events")
    op.drop_table("research_events")
    op.drop_index("ix_research_jobs_claimable", table_name="research_jobs")
    op.drop_index("ix_research_jobs_user_id", table_name="research_jobs")
    op.drop_table("research_jobs")
