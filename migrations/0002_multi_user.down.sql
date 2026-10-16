-- 0002_multi_user.down.sql
-- Rollback for 0002_multi_user.up.sql. Rehearse on staging first (docs/migration-runbook.md).
-- Rows are kept. What is undone: owner separation, per-owner uniqueness, the policies, api_tokens and the
-- owner column. The global unique constraints and indexes are restored EXACTLY as they were before the
-- up migration, from public.migration_0002_saved_constraints (written by the up migration in step 3).
-- Receipt objects moved to <owner>/YYYY/MM/... can stay where they are: each row's receipt_path is the
-- source of truth, and the pre-step-2 code signs whatever path the row holds. No object move is needed here.

begin;

-- 0. The snapshot must exist: without it there is no record of the original constraints.
do $$
begin
  if to_regclass('public.migration_0002_saved_constraints') is null then
    raise exception 'public.migration_0002_saved_constraints is missing: the original constraints cannot be restored';
  end if;
end $$;

-- 1. Storage and table policies.
drop policy if exists receipts_owner_delete on storage.objects;
drop policy if exists receipts_owner_insert on storage.objects;
drop policy if exists receipts_owner_select on storage.objects;

drop table if exists public.api_tokens;

drop policy if exists transactions_owner_delete on public.transactions;
drop policy if exists transactions_owner_update on public.transactions;
drop policy if exists transactions_owner_insert on public.transactions;
drop policy if exists transactions_owner_select on public.transactions;

-- 2. Per-owner uniqueness and the listing index. `transactions_user_image_key` is the constraint an earlier
--    revision of the up file created; the current one creates the partial unique index
--    `transactions_user_image_uidx` instead, so both spellings are dropped here.
alter table public.transactions drop constraint if exists transactions_user_image_key;
alter table public.transactions drop constraint if exists transactions_user_dedupe_key;
drop index if exists public.transactions_user_image_uidx;
drop index if exists public.transactions_user_image_key;
drop index if exists public.transactions_user_mode_txn_date_idx;

-- 3. Global uniqueness comes back as it was. This fails if two owners now share a dedupe hash (or an image
--    hash): resolve those first, because the original global constraint cannot hold them. The image side
--    matches the original object's own terms — live's index is partial, so only non-null image_hash values
--    are held to it.
do $$
begin
  if exists (
    select 1 from public.transactions
     where dedupe_hash is not null
     group by dedupe_hash
    having count(*) > 1
  ) then
    raise exception 'the same dedupe_hash exists for two owners; resolve before rolling back';
  end if;
  if exists (
    select 1 from public.transactions
     where image_hash is not null
     group by image_hash
    having count(*) > 1
  ) then
    raise exception 'the same image_hash exists for two owners; resolve before rolling back';
  end if;
end $$;

do $$
declare
  r record;
begin
  for r in
    select definition from public.migration_0002_saved_constraints order by kind, name
  loop
    execute r.definition;
  end loop;
end $$;

-- 3a. What was restored must match what was saved: every snapshot row is now a unique index on one of the
--     two columns, and no extra global unique on them came back. Same catalog test as the up migration.
do $$
declare
  saved    int;
  restored int;
begin
  select count(*) into saved from public.migration_0002_saved_constraints;
  select count(*) into restored
    from pg_index i
    join pg_class t  on t.oid = i.indrelid
    join pg_namespace n on n.oid = t.relnamespace
   where n.nspname = 'public'
     and t.relname = 'transactions'
     and i.indisunique
     and not i.indisprimary
     and i.indnkeyatts = 1
     and (select a.attname
            from pg_attribute a
           where a.attrelid = i.indrelid and a.attnum = i.indkey[0])
         in ('dedupe_hash', 'image_hash');
  if restored <> saved then
    raise exception 'rollback restored % global unique object(s) but the snapshot holds %: the table is not back to its original shape', restored, saved;
  end if;
end $$;

-- 4. Owner column, then the snapshot itself.
alter table public.transactions drop column if exists user_id;
drop table if exists public.migration_0002_saved_constraints;

commit;
