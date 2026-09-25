ALTER TABLE document_pages
    ADD COLUMN IF NOT EXISTS page_kind text,
    ADD COLUMN IF NOT EXISTS routing_version text,
    ADD COLUMN IF NOT EXISTS requires_ocr boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS requires_vision boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS structure_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS page_blocks (
    block_id uuid PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES analysis_runs(run_id),
    case_id uuid NOT NULL REFERENCES cases(case_id),
    document_id uuid NOT NULL REFERENCES documents(document_id),
    document_version integer NOT NULL,
    page_index integer NOT NULL CHECK (page_index >= 0),
    block_type text NOT NULL CHECK (block_type IN ('title', 'paragraph', 'table', 'image', 'caption', 'unknown')),
    reading_order integer NOT NULL CHECK (reading_order >= 0),
    text_content text,
    bbox jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    extraction_method text NOT NULL,
    source_hash char(64) NOT NULL,
    parser_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, document_id, document_version, page_index, reading_order)
);
CREATE INDEX IF NOT EXISTS page_blocks_document_page_idx
    ON page_blocks(document_id, document_version, page_index, reading_order);
