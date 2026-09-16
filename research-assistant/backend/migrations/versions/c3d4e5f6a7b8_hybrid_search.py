"""Full-text index on rag_chunks, for hybrid retrieval.

Vector search alone misses exact strings — error codes, part numbers, proper
nouns, version numbers. Embeddings put "Sev-1" and "Sev-2" in almost the same
place, which is precisely wrong when the user asked about one of them.
Keyword search has the opposite failure (no synonyms, no paraphrase), so the
two are run together and their rankings fused.

A generated column rather than a trigger: Postgres keeps it in step with
content automatically, and there is no way for an INSERT path to forget it.
"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_content_tsv "
        "ON rag_chunks USING gin (content_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_content_tsv")
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS content_tsv")
