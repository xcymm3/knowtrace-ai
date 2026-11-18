alter table public.agent_runs add column approval_history jsonb not null default '[]'::jsonb
  check (jsonb_typeof(approval_history) = 'array');
