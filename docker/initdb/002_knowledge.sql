CREATE TABLE IF NOT EXISTS knowledge_parents (
    parent_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    title TEXT NOT NULL,
    section_path TEXT NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    scope_kind TEXT GENERATED ALWAYS AS (
        CASE
            WHEN product_id IN ('STORE', 'PLATFORM') THEN lower(product_id)
            ELSE 'product'
        END
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES knowledge_parents(parent_id) ON DELETE CASCADE,
    doc_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    title TEXT NOT NULL,
    section_path TEXT NOT NULL,
    unit_kind TEXT NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    scope_kind TEXT GENERATED ALWAYS AS (
        CASE
            WHEN product_id IN ('STORE', 'PLATFORM') THEN lower(product_id)
            ELSE 'product'
        END
    ) STORED,
    embedding vector(1024) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_product
    ON knowledge_chunks (product_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc
    ON knowledge_chunks (doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_scope
    ON knowledge_chunks (scope_kind, product_id);
CREATE INDEX IF NOT EXISTS idx_parents_scope
    ON knowledge_parents (scope_kind, product_id);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata
    ON knowledge_chunks USING gin (metadata);

CREATE TABLE IF NOT EXISTS knowledge_state (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO knowledge_state (id, version)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;
