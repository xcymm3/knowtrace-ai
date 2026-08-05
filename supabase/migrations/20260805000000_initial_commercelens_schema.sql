-- CommerceLens AI MVP schema.
-- FastAPI is the only data-access layer in the MVP and uses Supabase's
-- service-role key. RLS is enabled now so later user-scoped policies can be
-- added without changing table ownership.

create extension if not exists vector;

create type public.project_status as enum ('DRAFT', 'ACTIVE', 'ARCHIVED');
create type public.product_role as enum ('OWN', 'COMPETITOR');
create type public.document_kind as enum (
  'PRODUCT_SHEET',
  'COMPETITOR_SHEET',
  'BRAND_GUIDE',
  'PLATFORM_RULE',
  'REVIEW_EXPORT',
  'PRODUCT_IMAGE',
  'COMPETITOR_SCREENSHOT',
  'OTHER'
);
create type public.document_status as enum ('PENDING', 'PROCESSING', 'READY', 'FAILED');
create type public.task_type as enum ('PARSE_DOCUMENT', 'GENERATE_EMBEDDINGS', 'COMPARE_PRODUCTS', 'GENERATE_REPORT');
create type public.task_status as enum ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED');
create type public.report_status as enum ('DRAFT', 'READY_FOR_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED');
create type public.finding_type as enum ('RECOMMENDATION', 'DIFFERENTIATOR', 'RISK', 'AUDIENCE_INSIGHT', 'CONTENT_STRATEGY');
create type public.review_decision as enum ('APPROVED', 'REJECTED', 'NEEDS_REVISION');

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = timezone('utc', now());
  return new;
end;
$$;

create table public.research_projects (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 1 and 120),
  category text,
  target_platform text,
  target_audience text,
  status public.project_status not null default 'DRAFT',
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.brand_profiles (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null unique references public.research_projects(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 120),
  tone text,
  forbidden_terms text[] not null default '{}',
  guidelines jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.products (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.research_projects(id) on delete cascade,
  role public.product_role not null,
  name text not null check (char_length(trim(name)) between 1 and 200),
  brand_name text,
  external_url text,
  price numeric(12, 2) check (price is null or price >= 0),
  currency char(3),
  description text,
  attributes jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.source_documents (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.research_projects(id) on delete cascade,
  product_id uuid references public.products(id) on delete set null,
  kind public.document_kind not null,
  file_name text not null check (char_length(trim(file_name)) between 1 and 255),
  mime_type text not null,
  size_bytes bigint not null check (size_bytes >= 0),
  storage_bucket text not null default 'research-assets',
  storage_path text not null unique,
  checksum text,
  status public.document_status not null default 'PENDING',
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  check (storage_path like project_id::text || '/%')
);

create table public.knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.source_documents(id) on delete cascade,
  chunk_index integer not null check (chunk_index >= 0),
  content text not null check (char_length(trim(content)) > 0),
  token_count integer check (token_count is null or token_count > 0),
  embedding vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  unique (document_id, chunk_index)
);

create table public.research_tasks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.research_projects(id) on delete cascade,
  document_id uuid references public.source_documents(id) on delete cascade,
  task_type public.task_type not null,
  status public.task_status not null default 'QUEUED',
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

create table public.selection_reports (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.research_projects(id) on delete cascade,
  task_id uuid unique references public.research_tasks(id) on delete set null,
  title text not null check (char_length(trim(title)) between 1 and 200),
  summary text,
  status public.report_status not null default 'DRAFT',
  generation_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create table public.report_findings (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.selection_reports(id) on delete cascade,
  type public.finding_type not null,
  title text not null check (char_length(trim(title)) between 1 and 200),
  content text not null check (char_length(trim(content)) > 0),
  confidence numeric(4, 3) check (confidence is null or confidence between 0 and 1),
  position integer not null check (position >= 1),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),
  unique (report_id, position)
);

create table public.finding_citations (
  id uuid primary key default gen_random_uuid(),
  finding_id uuid not null references public.report_findings(id) on delete cascade,
  chunk_id uuid not null references public.knowledge_chunks(id) on delete restrict,
  excerpt text not null check (char_length(trim(excerpt)) between 1 and 800),
  position integer not null check (position >= 1),
  created_at timestamptz not null default timezone('utc', now()),
  unique (finding_id, position)
);

create table public.review_feedback (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.selection_reports(id) on delete cascade,
  finding_id uuid references public.report_findings(id) on delete cascade,
  decision public.review_decision not null,
  comment text,
  reviewer_label text not null default 'MVP Reviewer',
  created_at timestamptz not null default timezone('utc', now())
);

create index products_project_role_idx on public.products(project_id, role);
create index source_documents_project_status_idx on public.source_documents(project_id, status);
create index source_documents_product_idx on public.source_documents(product_id) where product_id is not null;
create index knowledge_chunks_document_idx on public.knowledge_chunks(document_id, chunk_index);
create index knowledge_chunks_embedding_idx on public.knowledge_chunks using hnsw (embedding vector_cosine_ops) where embedding is not null;
create index research_tasks_project_status_idx on public.research_tasks(project_id, status, created_at desc);
create index selection_reports_project_status_idx on public.selection_reports(project_id, status, created_at desc);
create index report_findings_report_idx on public.report_findings(report_id, position);
create index finding_citations_finding_idx on public.finding_citations(finding_id, position);
create index review_feedback_report_idx on public.review_feedback(report_id, created_at desc);

create trigger research_projects_set_updated_at
before update on public.research_projects
for each row execute function public.set_updated_at();

create trigger brand_profiles_set_updated_at
before update on public.brand_profiles
for each row execute function public.set_updated_at();

create trigger products_set_updated_at
before update on public.products
for each row execute function public.set_updated_at();

create trigger source_documents_set_updated_at
before update on public.source_documents
for each row execute function public.set_updated_at();

create trigger research_tasks_set_updated_at
before update on public.research_tasks
for each row execute function public.set_updated_at();

create trigger selection_reports_set_updated_at
before update on public.selection_reports
for each row execute function public.set_updated_at();

create trigger report_findings_set_updated_at
before update on public.report_findings
for each row execute function public.set_updated_at();

alter table public.research_projects enable row level security;
alter table public.brand_profiles enable row level security;
alter table public.products enable row level security;
alter table public.source_documents enable row level security;
alter table public.knowledge_chunks enable row level security;
alter table public.research_tasks enable row level security;
alter table public.selection_reports enable row level security;
alter table public.report_findings enable row level security;
alter table public.finding_citations enable row level security;
alter table public.review_feedback enable row level security;
