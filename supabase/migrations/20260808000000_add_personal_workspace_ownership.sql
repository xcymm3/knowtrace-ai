-- Personal workspaces: every newly created workspace belongs to one Supabase Auth user.
-- Existing MVP rows intentionally remain unassigned. After creating the first account,
-- an administrator may explicitly assign legacy rows with an UPDATE in the SQL editor.

alter table public.workspaces
  add column if not exists owner_id uuid references auth.users(id) on delete cascade;

create index if not exists workspaces_owner_updated_idx
  on public.workspaces(owner_id, updated_at desc);

drop policy if exists "personal workspaces" on public.workspaces;
create policy "personal workspaces"
  on public.workspaces
  for all
  to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists "personal workspace documents" on public.workspace_documents;
create policy "personal workspace documents"
  on public.workspace_documents
  for all
  to authenticated
  using (
    exists (
      select 1 from public.workspaces
      where workspaces.id = workspace_documents.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.workspaces
      where workspaces.id = workspace_documents.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  );

drop policy if exists "personal document chunks" on public.document_chunks;
create policy "personal document chunks"
  on public.document_chunks
  for all
  to authenticated
  using (
    exists (
      select 1 from public.workspaces
      where workspaces.id = document_chunks.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.workspaces
      where workspaces.id = document_chunks.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  );

drop policy if exists "personal processing tasks" on public.processing_tasks;
create policy "personal processing tasks"
  on public.processing_tasks
  for all
  to authenticated
  using (
    exists (
      select 1 from public.workspaces
      where workspaces.id = processing_tasks.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.workspaces
      where workspaces.id = processing_tasks.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  );

drop policy if exists "personal conversations" on public.conversations;
create policy "personal conversations"
  on public.conversations
  for all
  to authenticated
  using (
    exists (
      select 1 from public.workspaces
      where workspaces.id = conversations.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from public.workspaces
      where workspaces.id = conversations.workspace_id
        and workspaces.owner_id = auth.uid()
    )
  );

drop policy if exists "personal conversation messages" on public.conversation_messages;
create policy "personal conversation messages"
  on public.conversation_messages
  for all
  to authenticated
  using (
    exists (
      select 1
      from public.conversations
      join public.workspaces on workspaces.id = conversations.workspace_id
      where conversations.id = conversation_messages.conversation_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.conversations
      join public.workspaces on workspaces.id = conversations.workspace_id
      where conversations.id = conversation_messages.conversation_id
        and workspaces.owner_id = auth.uid()
    )
  );

drop policy if exists "personal message citations" on public.message_citations;
create policy "personal message citations"
  on public.message_citations
  for all
  to authenticated
  using (
    exists (
      select 1
      from public.conversation_messages
      join public.conversations on conversations.id = conversation_messages.conversation_id
      join public.workspaces on workspaces.id = conversations.workspace_id
      where conversation_messages.id = message_citations.message_id
        and workspaces.owner_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.conversation_messages
      join public.conversations on conversations.id = conversation_messages.conversation_id
      join public.workspaces on workspaces.id = conversations.workspace_id
      where conversation_messages.id = message_citations.message_id
        and workspaces.owner_id = auth.uid()
    )
  );
