-- 0002_multi_user.down.sql
-- Rollback for 0002_multi_user.up.sql. NOT EXECUTED. Rehearse on staging first.
-- Rows are kept. What is undone: owner separation, per-owner uniqueness, the policies and api_tokens.
-- Receipt objects moved to <owner>/YYYY/MM/... must be moved back with the reverse script, not here.

begin;

-- 1. Storage and table policies.
drop policy if exists receipts_owner_delete on storage.objects;
drop policy if exists receipts_owner_insert on storage.objects;
drop policy if exists receipts_owner_select on storage.objects;

drop table if exists public.api_tokens;

drop policy if exists transactions_owner_delete on public.transactions;
drop policy if exists transactions_owner_update on public.transactions;
drop policy if exists transactions_owner_insert on public.transactions;
drop policy if exists transactions_owner_select on public.transactions;

-- 2. Per-owner indexes.
drop index if exists public.transactions_user_mode_txn_date_idx;
drop index if exists public.transactions_user_image_key;
drop index if exists public.transactions_user_dedupe_key;

-- 3. Global uniqueness is restored. This fails if two owners now share a dedupe hash: resolve those first.
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
end $$;
alter table public.transactions add constraint transactions_dedupe_hash_key unique (dedupe_hash);
-- VERIFY against the audit (scripts/audit_queries.sql, section B) before running: restore image_hash
-- uniqueness only if the live table had it before step 2.
alter table public.transactions add constraint transactions_image_hash_key unique (image_hash);

-- 4. Owner column.
alter table public.transactions drop column if exists user_id;

commit;
