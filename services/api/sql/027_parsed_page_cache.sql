CREATE TABLE IF NOT EXISTS parsed_page_cache (
    document_id uuid NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    document_version integer NOT NULL,
    source_hash char(64) NOT NULL,
    parser_fingerprint char(64) NOT NULL,
    page_index integer NOT NULL CHECK (page_index >= 0),
    page_payload jsonb NOT NULL,
    payload_sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, document_version, source_hash, parser_fingerprint, page_index)
);
