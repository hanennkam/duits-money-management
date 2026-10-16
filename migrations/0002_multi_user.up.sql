-- 0002_multi_user.up.sql
-- NOT EXECUTED on live. Rehearse on a staging Supabase project first (docs/migration-runbook.md).
-- Run in ONE session (the Supabase SQL editor runs a script in one session), as the first statement:
--   select set_config('app.owner_id', '<your auth.users id>', false);
-- Nothing in this file contains a real user id. The guard below stops the run if it is missing.
-- Every step either does what it says or raises: a silent no-op is a failed migration.

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

-- 3. The global uniqueness of dedupe_hash and image_hash goes away; per-owner uniqueness replaces it (step 4).
--    Both objects are identified in the CATALOG from here on, never by matching indexdef text, because live
--    carries the image_hash uniqueness as a PARTIAL unique index. Its definition ends in
--    `WHERE (image_hash IS NOT NULL)`, so any pattern anchored on `(image_hash)$` misses it — and a missed
--    index means a silent no-op that leaves image_hash globally unique, which would stop a second owner from
--    ever scanning the same photo.
--    3a. Save the exact definitions first, so the rollback restores precisely what was there: the same object
--    kind, the same name, and the same definition verbatim, WHERE clause included.
create table if not exists public.migration_0002_saved_constraints (
  kind       text not null,  -- 'constraint' or 'index'
  name       text not null,
  definition text not null
);

-- One row per unique index on public.transactions whose ONLY key column is dedupe_hash or image_hash,
-- primary keys excluded. Constraint-backed ones are saved as the constraint (that is the object to restore);
-- the rest are saved as the index definition exactly as Postgres reports it. Partial or not is irrelevant:
-- the key columns come from pg_index.indkey, not from the text.
insert into public.migration_0002_saved_constraints (kind, name, definition)
select case when c.oid is null then 'index' else 'constraint' end,
       ci.relname,
       case when c.oid is null then pg_get_indexdef(i.indexrelid)
            else 'alter table public.transactions add constraint '
                 || quote_ident(c.conname) || ' ' || pg_get_constraintdef(c.oid)
       end
  from pg_index i
  join pg_class t  on t.oid = i.indrelid
  join pg_namespace n on n.oid = t.relnamespace
  join pg_class ci on ci.oid = i.indexrelid
  left join pg_constraint c on c.conindid = i.indexrelid
 where n.nspname = 'public'
   and t.relname = 'transactions'
   and i.indisunique
   and not i.indisprimary
   and i.indnkeyatts = 1
   and (select a.attname
          from pg_attribute a
         where a.attrelid = i.indrelid and a.attnum = i.indkey[0])
       in ('dedupe_hash', 'image_hash');

-- 3b. Drop them. First the names live and staging actually carry, including live's partial index
--     transactions_image_hash_uidx, then a catalog walk that catches any other global unique on these two
--     columns whatever it is called and whether or not it is partial. A constraint is dropped as a
--     constraint and a loose index as an index, because dropping the index behind a constraint fails.
alter table public.transactions drop constraint if exists transactions_dedupe_hash_key;
alter table public.transactions drop constraint if exists transactions_image_hash_key;
drop index if exists public.transactions_dedupe_hash_key;
drop index if exists public.transactions_image_hash_key;
drop index if exists public.transactions_image_hash_uidx;

do $$
declare
  r record;
begin
  for r in
    select ci.relname as object_name,
           (c.oid is not null) as is_constraint
      from pg_index i
      join pg_class t  on t.oid = i.indrelid
      join pg_namespace n on n.oid = t.relnamespace
      join pg_class ci on ci.oid = i.indexrelid
      left join pg_constraint c on c.conindid = i.indexrelid
     where n.nspname = 'public'
       and t.relname = 'transactions'
       and i.indisunique
       and not i.indisprimary
       and i.indnkeyatts = 1
       and (select a.attname
              from pg_attribute a
             where a.attrelid = i.indrelid and a.attnum = i.indkey[0])
           in ('dedupe_hash', 'image_hash')
  loop
    if r.is_constraint then
      execute format('alter table public.transactions drop constraint %I', r.object_name);
    else
      execute format('drop index if exists public.%I', r.object_name);
    end if;
  end loop;
end $$;

-- 3c. Refuse to continue if a global unique on these columns is still there. This is the check that would
--     have caught the silent no-op. Same catalog test as 3a: partial or not, whatever the name.
do $$
declare
  survivor text;
begin
  select ci.relname || ' (' || pg_get_indexdef(i.indexrelid) || ')'
    into survivor
    from pg_index i
    join pg_class t  on t.oid = i.indrelid
    join pg_namespace n on n.oid = t.relnamespace
    join pg_class ci on ci.oid = i.indexrelid
   where n.nspname = 'public'
     and t.relname = 'transactions'
     and i.indisunique
     and not i.indisprimary
     and i.indnkeyatts = 1
     and (select a.attname
            from pg_attribute a
           where a.attrelid = i.indrelid and a.attnum = i.indkey[0])
         in ('dedupe_hash', 'image_hash')
   limit 1;
  if survivor is not null then
    raise exception 'a global unique on dedupe_hash or image_hash survived step 3; nothing after this point ran: %', survivor;
  end if;
end $$;

-- 4. Per-owner uniqueness, mirroring the two shapes it replaces: dedupe_hash keeps a constraint, and
--    image_hash becomes a PARTIAL unique index like live's, so rows with no image (typed entries, bank
--    screenshots) are outside it and a row's NULL image_hash never collides. NULLs are distinct inside a
--    unique constraint, so dedupe_hash NULL rows never collide either.
alter table public.transactions
  add constraint transactions_user_dedupe_key unique (user_id, dedupe_hash);
create unique index transactions_user_image_uidx
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
-- receipt_path is a script, not SQL: scripts/migrate_receipts.py, run after this file. The old paths stay
-- valid until that script has run and been verified.

commit;
