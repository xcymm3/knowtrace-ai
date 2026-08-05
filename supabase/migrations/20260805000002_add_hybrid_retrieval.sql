-- Hybrid retrieval keeps every result tied to an uploaded research document.
-- The database currently fixes vectors at 1536 dimensions (see initial schema).

alter table public.knowledge_chunks
  add column if not exists search_vector tsvector
  generated always as (to_tsvector('simple', content)) stored;

create index if not exists knowledge_chunks_search_vector_idx
  on public.knowledge_chunks using gin (search_vector);

create or replace function public.match_knowledge_chunks(
  p_project_id uuid,
  p_query_embedding vector(1536),
  p_query_text text,
  p_match_count integer default 8,
  p_document_kind public.document_kind default null,
  p_product_id uuid default null
)
returns table (
  id uuid,
  document_id uuid,
  content text,
  metadata jsonb,
  file_name text,
  kind public.document_kind,
  product_id uuid,
  semantic_score double precision,
  keyword_score double precision,
  final_score double precision
)
language sql
stable
set search_path = public
as $$
  with scored as (
    select
      chunk.id,
      chunk.document_id,
      chunk.content,
      chunk.metadata,
      document.file_name,
      document.kind,
      document.product_id,
      greatest(0::double precision, 1 - (chunk.embedding <=> p_query_embedding)) as semantic_score,
      ts_rank_cd(
        chunk.search_vector,
        websearch_to_tsquery('simple', coalesce(nullif(trim(p_query_text), ''), ''))
      )::double precision as keyword_score
    from public.knowledge_chunks as chunk
    join public.source_documents as document on document.id = chunk.document_id
    where document.project_id = p_project_id
      and document.status = 'READY'
      and chunk.embedding is not null
      and (p_document_kind is null or document.kind = p_document_kind)
      and (p_product_id is null or document.product_id = p_product_id)
  )
  select
    id,
    document_id,
    content,
    metadata,
    file_name,
    kind,
    product_id,
    semantic_score,
    keyword_score,
    (semantic_score * 0.75 + keyword_score * 0.25)::double precision as final_score
  from scored
  order by final_score desc, id
  limit least(greatest(p_match_count, 1), 20);
$$;

revoke all on function public.match_knowledge_chunks(
  uuid, vector(1536), text, integer, public.document_kind, uuid
) from public, anon, authenticated;
grant execute on function public.match_knowledge_chunks(
  uuid, vector(1536), text, integer, public.document_kind, uuid
) to service_role;
