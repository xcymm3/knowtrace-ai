-- Usernames are stored separately from auth.users so they can be unique and
-- resolved by the trusted FastAPI sign-in endpoint without exposing user emails.

create extension if not exists citext;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username citext not null unique check (username ~ '^[A-Za-z0-9_-]{3,32}$'),
  email text not null,
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists profiles_username_idx on public.profiles(username);

alter table public.profiles enable row level security;

drop policy if exists "profiles readable by owner" on public.profiles;
create policy "profiles readable by owner"
  on public.profiles
  for select
  to authenticated
  using (id = auth.uid());

create or replace function public.create_profile_for_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
declare
  normalized_username text;
begin
  normalized_username := lower(trim(coalesce(new.raw_user_meta_data ->> 'username', '')));
  if normalized_username !~ '^[A-Za-z0-9_-]{3,32}$' then
    raise exception '用户名需为 3–32 位字母、数字、下划线或连字符';
  end if;

  insert into public.profiles (id, username, email)
  values (new.id, normalized_username, coalesce(new.email, ''));
  return new;
end;
$$;

drop trigger if exists create_profile_after_auth_user on auth.users;
create trigger create_profile_after_auth_user
  after insert on auth.users
  for each row execute procedure public.create_profile_for_new_user();

with existing_auth_users as (
  select
    auth_user.id,
    auth_user.email,
    lower(nullif(trim(auth_user.raw_user_meta_data ->> 'username'), '')) as requested_username
  from auth.users as auth_user
)
insert into public.profiles (id, username, email)
select
  id,
  case
    when requested_username ~ '^[A-Za-z0-9_-]{3,32}$'
      and count(*) over (partition by requested_username) = 1
    then requested_username
    else 'user-' || left(id::text, 8)
  end,
  coalesce(email, '')
from existing_auth_users
on conflict (id) do nothing;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();
