-- Parsing and vector indexing are separate stages in KnowTrace.
alter type public.knowledge_document_status add value if not exists 'PARSED' after 'PROCESSING';
