-- 0002_multi_user.up.sql
-- NOT EXECUTED. Rehearse on a staging Supabase project first (see docs/multi-user-step2.md).
-- Run in ONE session (the Supabase SQL editor runs a script in one session), as the first statement:
--   select set_config('app.owner_id', '<your auth.users id>', false);
-- Nothing in this file contains a real user id. The guard below stops the run if it is missing.

begin;

-- 0. Guard: the owner must be set in this session.
do $$
begin
  if coalesce(current_setting('app.owner_id', true), '') = '' then
    raise exception 'set app.owner_id first: select set_config(''app.owner_id'', ''<auth.users id>'', false);';
  end if;
end $$;

-- 1. Owner column. Nullable for now: the step-1 code keeps inserting rows without an owner until step 2 is live.
alter table public.transactions add column if not exists user_id uuid references auth.users(id);

-- 2. Backfill every existing row to the owner (the account that uses the app today).
update public.transactions
   set user_id = current_setting('app.owner_id')::uuid
 where user_id is null;

-- 3. Global unique constraints on dedupe_hash / image_hash become per owner.
--    Found by catalog lookup, not by name, because the live constraint names are not in schema.sql.
do $$
declare
  r record;
begin
  for r in
    select conname
      from pg_constraint
     where conrelid = 'public.transactions'::regclass
       and contype = 'u'
       and pg_get_constraintdef(oid) ~ '\m(dedupe_hash|image_hash)\m'
  loop
    execute format('alter table public.transactions drop constraint %I', r.conname);
  end loop;

  -- unique indexes that are not constraints
  for r in
    select indexname
      from pg_indexes
     where schemaname = 'public'
       and tablename = 'transactions'
       and indexdef ~* 'create unique index'
       and indexdef ~ '\m(dedupe_hash|image_hash)\m'
  loop
    execute format('drop index public.%I', r.indexname);
  end loop;
end $$;

-- 4. Per-owner uniqueness. Partial, so NULL hashes (text entries, typed rows) never collide.
create unique index if not exists transactions_user_dedupe_key
  on public.transactions (user_id, dedupe_hash) where dedupe_hash is not null;
create unique index if not exists transactions_user_image_key
  on public.transactions (user_id, image_hash) where image_hash is not null;

-- 5. Listing index for one owner's month.
create index if not exists transactions_user_mode_txn_date_idx
  on public.transactions (user_id, mode, txn_date desc);

-- 6. NOT NULL, only when no row lacks an owner. Run this after the step-2 code is live: old code still
--    writing rows would make this raise, which is the point.
do $$
begin
  if exists (select 1 from public.transactions where user_id is null) then
    raise exception 'rows without an owner exist; finish the backfill before setting NOT NULL';
  end if;
end $$;
alter table public.transactions alter column user_id set not null;

-- 7. Row-level security. The API uses the service key, which bypasses RLS, so these policies are the
--    backstop for any other key or any direct client access. RLS itself is already on (schema.sql).
create policy transactions_owner_select on public.transactions
  for select to authenticated using (user_id = auth.uid());
create policy transactions_owner_insert on public.transactions
  for insert to authenticated with check (user_id = auth.uid());
create policy transactions_owner_update on public.transactions
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy transactions_owner_delete on public.transactions
  for delete to authenticated using (user_id = auth.uid());

-- 8. Personal access tokens for the iOS Shortcut: a random token shown once, stored as a SHA-256 hash.
create table if not exists public.api_tokens (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  token_hash   text not null unique,
  label        text,
  created_at   timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at   timestamptz
);
-- RLS on with no policies: only the service key (the API) can read or write this table.
alter table public.api_tokens enable row level security;

-- 9. Storage: a signed-in user may touch only objects under their own folder (user_id/...).
--    The API writes with the service key; these are the backstop. The bucket stays private.
create policy receipts_owner_select on storage.objects
  for select to authenticated
  using (bucket_id = 'receipts' and (storage.foldername(name))[1] = auth.uid()::text);
create policy receipts_owner_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'receipts' and (storage.foldername(name))[1] = auth.uid()::text);
create policy receipts_owner_delete on storage.objects
  for delete to authenticated
  using (bucket_id = 'receipts' and (storage.foldername(name))[1] = auth.uid()::text);

-- Existing objects still sit at YYYY/MM/<uuid>.jpg. Moving them to <owner>/YYYY/MM/<uuid>.jpg and updating
-- receipt_path is a script, not SQL (storage objects are moved through the Storage API). Do it in staging.

commit;
