# Owner: Ali

"""Add Ali RAG CMS and pgvector embedding columns.

Revision ID: 002_ali_rag_pgvector
Revises: 001
Create Date: 2026-05-30
"""

from typing import Sequence, Union

from alembic import op


revision: str = "002_ali_rag_pgvector"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS content_id TEXT")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS title TEXT")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS body TEXT")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS url TEXT")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'page'")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS locale TEXT DEFAULT 'en'")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS published BOOLEAN DEFAULT true")
    op.execute("ALTER TABLE cms_content ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cms_content_tenant_content_id
        ON cms_content (tenant_id, content_id)
    """)

    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_id TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS cms_content_id TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS title TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS text TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS url TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'page'")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS page_id TEXT")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS locale TEXT DEFAULT 'en'")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS published BOOLEAN DEFAULT true")
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_tenant_chunk_id
        ON embeddings (tenant_id, chunk_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_embeddings_tenant_vector
        ON embeddings USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_embeddings_tenant_vector")
    op.execute("DROP INDEX IF EXISTS idx_embeddings_tenant_chunk_id")
    op.execute("DROP INDEX IF EXISTS idx_cms_content_tenant_content_id")
