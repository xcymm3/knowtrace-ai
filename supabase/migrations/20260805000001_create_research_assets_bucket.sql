-- The MVP stores original research materials in a private bucket. Browser
-- clients never access Storage directly: FastAPI uses the service-role key
-- and will later issue short-lived signed URLs for approved downloads.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'research-assets',
  'research-assets',
  false,
  52428800,
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
    'text/csv',
    'image/jpeg',
    'image/png',
    'image/webp'
  ]
)
on conflict (id) do update
set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

-- No storage.objects policy is created in the MVP. With Storage RLS enabled,
-- this denies direct anon/authenticated access by default. The server-side
-- Supabase service-role client bypasses RLS and remains the sole file gateway.
