"""Vector and FK indexes for rag_chunks.

Separate from the baseline on purpose: a database that predates Alembic is
stamped at the baseline rather than running it, so anything the baseline
contains never reaches those databases. New work goes in new revisions.

Without the HNSW index every similarity search scans and scores every chunk in
the table — invisible at a few thousand, the whole latency budget at a million.
The document_id index backs the join retrieval performs; Postgres does not
create one for a foreign key on its own.
"""
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "7f7f8a5112e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw "
        "ON rag_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_document_id ON rag_chunks (document_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_document_id")
