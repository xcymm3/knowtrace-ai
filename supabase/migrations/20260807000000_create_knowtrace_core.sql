-- KnowTrace core model. This migration is additive: existing CommerceLens
-- tables remain untouched so a deployed prototype can be upgraded safely.

create type public.workspace_status as enum ('DRAFT', 'ACTIVE', 'ARCHIVED');
create type public.knowledge_document_kind as enum ('GENERAL', 'REFERENCE', 'NOTE', 'DATASET', 'IMAGE');
create type public.knowledge_document_status as enum ('PENDING', 'PROCESSING', 'READY', 'FAILED');
create type public.knowledge_task_type as enum ('PARSE_DOCUMENT', 'GENERATE_EMBEDDINGS');
create type public.knowledge_task_status as enum ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED');
create type public.knowledge_message_role as enum ('USER', 'ASSISTANT', 'SYSTEM');

create table public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 1 and 120),
  description text,
  status public.workspace_status not null default 'DRAFT',
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.workspace_documents (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  kind public.knowledge_document_kind not null default 'GENERAL',
  file_name text not null check (char_length(trim(file_name)) between 1 and 255),
  mime_type text not null,
  size_bytes bigint not null check (size_bytes >= 0),
  storage_bucket text not null default 'knowtrace-assets',
  storage_path text not null unique,
  checksum text,
  status public.knowledge_document_status not null default 'PENDING',
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  check (storage_path like workspace_id::text || '/%')
);

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  document_id uuid not null references public.workspace_documents(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null check (char_length(trim(content)) > 0),
  token_count integer check (token_count is null or token_count > 0),
  embedding vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  search_vector tsvector generated always as (to_tsvector('simple', content)) stored,
  created_at timestamptz not null default timezone('utc', now()),
  unique (document_id, chunk_index)
);

create table public.processing_tasks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  document_id uuid references public.workspace_documents(id) on delete cascade,
  task_type public.knowledge_task_type not null,
  status public.knowledge_task_status not null default 'QUEUED',
  progress smallint not null default 0 check (progress between 0 and 100),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  input_payload jsonb not null default '{}'::jsonb,
  output_payload jsonb not null default '{}'::jsonb,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  check (completed_at is null or started_at is null or completed_at >= started_at)
);

create table public.conversations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  title text not null default '新对话' check (char_length(trim(title)) between 1 and 160),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.conversation_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.conversations(id) on delete cascade,
  role public.knowledge_message_role not null,
  content text not null check (char_length(trim(content)) > 0),
  sequence integer not null check (sequence >= 0),
  retrieval_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  unique (conversation_id, sequence)
);

create table public.message_citations (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references public.conversation_messages(id) on delete cascade,
  chunk_id uuid not null references public.document_chunks(id) on delete restrict,
  excerpt text not null check (char_length(trim(excerpt)) between 1 and 1200),
  citation_order integer not null check (citation_order >= 1),
  created_at timestamptz not null default timezone('utc', now()),
  unique (message_id, citation_order)
);

create index workspace_documents_workspace_status_idx on public.workspace_documents(workspace_id, status, created_at desc);
create index document_chunks_workspace_document_idx on public.document_chunks(workspace_id, document_id, chunk_index);
create index document_chunks_embedding_idx on public.document_chunks using hnsw (embedding vector_cosine_ops) where embedding is not null;
create index document_chunks_search_idx on public.document_chunks using gin (search_vector);
create index processing_tasks_workspace_status_idx on public.processing_tasks(workspace_id, status, created_at desc);
create index conversations_workspace_updated_idx on public.conversations(workspace_id, updated_at desc);
create index conversation_messages_conversation_sequence_idx on public.conversation_messages(conversation_id, sequence);
create index message_citations_message_idx on public.message_citations(message_id, citation_order);

create or replace function public.match_document_chunks(
  p_workspace_id uuid,
  p_query_embedding vector(1536),
  p_query_text text,
  p_match_count integer default 8,
  p_document_kind public.knowledge_document_kind default null
)
returns table (
  id uuid,
  document_id uuid,
  content text,
  metadata jsonb,
  file_name text,
  kind public.knowledge_document_kind,
  semantic_score double precision,
  keyword_score double precision,
  final_score double precision
)
language sql stable set search_path = public as $$
  with scored as (
    select chunk.id, chunk.document_id, chunk.content, chunk.metadata,
      document.file_name, document.kind,
      greatest(0::double precision, 1 - (chunk.embedding <=> p_query_embedding)) as semantic_score,
      ts_rank_cd(chunk.search_vector, websearch_to_tsquery('simple', coalesce(nullif(trim(p_query_text), ''), '')))::double precision as keyword_score
    from public.document_chunks as chunk
    join public.workspace_documents as document on document.id = chunk.document_id
    where chunk.workspace_id = p_workspace_id
      and document.status = 'READY'
      and chunk.embedding is not null
      and (p_document_kind is null or document.kind = p_document_kind)
  )
  select id, document_id, content, metadata, file_name, kind, semantic_score, keyword_score,
    (semantic_score * 0.75 + keyword_score * 0.25)::double precision as final_score
  from scored order by final_score desc, id limit least(greatest(p_match_count, 1), 20);
$$;

revoke all on function public.match_document_chunks(uuid, vector(1536), text, integer, public.knowledge_document_kind) from public, anon, authenticated;
grant execute on function public.match_document_chunks(uuid, vector(1536), text, integer, public.knowledge_document_kind) to service_role;

create trigger workspaces_set_updated_at before update on public.workspaces for each row execute function public.set_updated_at();
create trigger workspace_documents_set_updated_at before update on public.workspace_documents for each row execute function public.set_updated_at();
create trigger processing_tasks_set_updated_at before update on public.processing_tasks for each row execute function public.set_updated_at();
create trigger conversations_set_updated_at before update on public.conversations for each row execute function public.set_updated_at();

alter table public.workspaces enable row level security;
alter table public.workspace_documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.processing_tasks enable row level security;
alter table public.conversations enable row level security;
alter table public.conversation_messages enable row level security;
alter table public.message_citations enable row level security;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('knowtrace-assets', 'knowtrace-assets', false, 52428800, array[
  'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'text/plain', 'text/markdown',
  'text/csv', 'image/jpeg', 'image/png', 'image/webp'
])
on conflict (id) do update set public = excluded.public, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;
