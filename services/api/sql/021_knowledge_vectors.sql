CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS knowledge_vector_sets (
    corpus_version text NOT NULL,
    model_id text NOT NULL,
    document_count integer NOT NULL CHECK (document_count > 0),
    vector_count integer NOT NULL CHECK (vector_count >= document_count),
    built_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (corpus_version, model_id)
);

CREATE TABLE IF NOT EXISTS knowledge_vectors (
    corpus_version text NOT NULL,
    model_id text NOT NULL,
    entry_id text NOT NULL,
    part_index integer NOT NULL CHECK (part_index >= 0),
    embedding public.vector(512) NOT NULL,
    PRIMARY KEY (corpus_version, model_id, entry_id, part_index),
    FOREIGN KEY (corpus_version, model_id)
        REFERENCES knowledge_vector_sets(corpus_version, model_id)
);
