CREATE TABLE documents (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_url    text NOT NULL UNIQUE,
    doc_type      text NOT NULL CHECK (doc_type IN ('safety_alert', 'panel_report', 'district_report')),
    listing_url   text NOT NULL,
    sha256        char(64) NOT NULL,
    retrieved_at  timestamptz NOT NULL,
    etag          text,
    last_modified text,
    raw_path      text NOT NULL,
    page_count    int NOT NULL CHECK (page_count > 0),
    image_only    boolean NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pages (
    document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    page_number int NOT NULL CHECK (page_number >= 1),
    text        text NOT NULL,
    image_only  boolean NOT NULL,
    char_count  int NOT NULL,
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE chunks (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunker        text NOT NULL,
    chunker_params jsonb NOT NULL,
    ordinal        int NOT NULL,
    page_start     int NOT NULL,
    page_end       int NOT NULL,
    text           text NOT NULL CHECK (length(text) > 0),
    char_count     int NOT NULL,
    word_count     int NOT NULL,
    UNIQUE (document_id, chunker, chunker_params, ordinal),
    CHECK (page_start >= 1 AND page_start <= page_end)
);
