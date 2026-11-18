create table public.agent_runs (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  executor_id uuid not null,
  claim_id uuid,
  task text not null check (char_length(trim(task)) between 1 and 8000),
  status text not null default 'QUEUED' check (
    status in ('QUEUED', 'RUNNING', 'WAITING_APPROVAL', 'APPLYING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
  ),
  revision integer not null default 0 check (revision >= 0),
  events jsonb not null default '[]'::jsonb check (jsonb_typeof(events) = 'array'),
  approval jsonb check (approval is null or jsonb_typeof(approval) = 'object'),
  cancel_requested boolean not null default false,
  executor_ops jsonb not null default '[]'::jsonb check (jsonb_typeof(executor_ops) = 'array'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index agent_runs_workspace_created_idx
  on public.agent_runs(workspace_id, created_at desc);
create index agent_runs_queued_executor_idx
  on public.agent_runs(workspace_id, executor_id, created_at) where status = 'QUEUED';
create unique index agent_runs_claim_idx
  on public.agent_runs(workspace_id, claim_id) where claim_id is not null;
create unique index agent_runs_active_executor_idx
  on public.agent_runs(workspace_id, executor_id)
  where status in ('RUNNING', 'WAITING_APPROVAL', 'APPLYING');

create trigger agent_runs_set_updated_at before update on public.agent_runs
  for each row execute function public.set_updated_at();

alter table public.agent_runs enable row level security;
revoke all on public.agent_runs from public, anon, authenticated;
grant select, insert, update on public.agent_runs to service_role;
