ALTER TABLE chunks ADD COLUMN section text CHECK (section IS NULL OR length(section) > 0);
CREATE INDEX chunks_chunker_document ON chunks (chunker, document_id);
