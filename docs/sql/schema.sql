CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    name_key    TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id        TEXT PRIMARY KEY,
    kb_id         TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    file_hash     TEXT NOT NULL,
    file_size     INTEGER NOT NULL,
    content_type  TEXT,
    chunk_count   INTEGER NOT NULL,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT NOT NULL,
    kb_id       TEXT NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding   vector(1024) NOT NULL,
    PRIMARY KEY (doc_id, id)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_kb_id_idx     ON chunks (kb_id);
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx    ON chunks (doc_id);
CREATE INDEX IF NOT EXISTS documents_kb_id_idx  ON documents (kb_id);
CREATE INDEX IF NOT EXISTS documents_uploaded_at_idx ON documents (uploaded_at DESC);

CREATE TABLE IF NOT EXISTS retrieve_logs (
    id           BIGSERIAL PRIMARY KEY,
    kb_ids       TEXT[] NOT NULL,
    query        TEXT NOT NULL,
    top_k        INTEGER NOT NULL,
    hit_count    INTEGER NOT NULL,
    latency_ms   INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS retrieve_logs_created_at_idx ON retrieve_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS retrieve_logs_kb_ids_idx     ON retrieve_logs USING GIN (kb_ids);
