-- 0003_budget_commitments.down.sql
-- Rollback for 0003_budget_commitments.up.sql. Rehearse on staging first (docs/migration-runbook.md).
--
-- Rolling back DESTROYS rows the owner typed in: the opening balance, the budget, every commitment and
-- every paid mark. That is not silent here: the guard below refuses until the operator acknowledges it,
-- and the rows are copied into public.migration_0003_saved_rows (jsonb) BEFORE the drop, so the snapshot
-- is the recovery path. Dropping that snapshot is a later, separate, owner-approved step — the same
-- discipline as public.migration_0002_saved_constraints.
--
-- Run in ONE session, as the first statement:
--   select set_config('app.allow_0003_data_loss', 'yes', false);
--
-- public.transactions is not touched in either direction: no column, no row, so 0002's indexes and the
-- 0002 rollback path are unaffected.

begin;

-- 0. Guard: the operator must acknowledge that this destroys user-entered data.
do $$
begin
  if coalesce(current_setting('app.allow_0003_data_loss', true), '') <> 'yes' then
    raise exception 'refusing: this drops user-entered settings, commitments and paid marks. Set app.allow_0003_data_loss to ''yes'' first.';
  end if;
end $$;

-- 1. The snapshot table. It holds user data, so it is RLS-protected the moment it exists: ENABLE + FORCE
--    with NO policies, exactly like public.api_tokens in 0002, so no anon/authenticated key can read it
--    through PostgREST (without RLS, a new table in `public` would be exposed).
--    The inserts below therefore run as a role that bypasses RLS — Supabase's SQL editor `postgres` is a
--    superuser and `service_role` has BYPASSRLS. If that were ever not the case they would raise and the
--    whole run would roll back: a loud failure, never a silent half-rollback.
create table if not exists public.migration_0003_saved_rows (
  table_name text not null,
  saved_at   timestamptz not null default now(),
  payload    jsonb not null
);
alter table public.migration_0003_saved_rows enable row level security;
alter table public.migration_0003_saved_rows force  row level security;

-- 2. Snapshot the rows, one entry per table, so the shape cannot drift.
insert into public.migration_0003_saved_rows (table_name, payload)
  select 'user_finance_settings', coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.user_finance_settings t;
insert into public.migration_0003_saved_rows (table_name, payload)
  select 'monthly_commitments', coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.monthly_commitments t;
insert into public.migration_0003_saved_rows (table_name, payload)
  select 'commitment_payments', coalesce(jsonb_agg(to_jsonb(t)), '[]'::jsonb) from public.commitment_payments t;

-- 3. The view first (it reads public.transactions, not these tables, but it is ours to remove), then the
--    policies, then the tables. Dropping a table drops its policies, so the explicit drops only make the
--    intent readable.
drop view if exists public.transaction_totals;

drop policy if exists finance_settings_owner_select on public.user_finance_settings;
drop policy if exists finance_settings_owner_insert on public.user_finance_settings;
drop policy if exists finance_settings_owner_update on public.user_finance_settings;
drop policy if exists finance_settings_owner_delete on public.user_finance_settings;
drop policy if exists commitments_owner_select on public.monthly_commitments;
drop policy if exists commitments_owner_insert on public.monthly_commitments;
drop policy if exists commitments_owner_update on public.monthly_commitments;
drop policy if exists commitments_owner_delete on public.monthly_commitments;
drop policy if exists commitment_payments_owner_select on public.commitment_payments;
drop policy if exists commitment_payments_owner_insert on public.commitment_payments;
drop policy if exists commitment_payments_owner_update on public.commitment_payments;
drop policy if exists commitment_payments_owner_delete on public.commitment_payments;

drop table if exists public.commitment_payments;
drop table if exists public.monthly_commitments;
drop table if exists public.user_finance_settings;

-- 4. What went must be gone, and the snapshot must be there, complete, and closed to anon/authenticated.
do $$
declare
  saved      int;
  leftovers  text;
begin
  if to_regclass('public.migration_0003_saved_rows') is null then
    raise exception 'public.migration_0003_saved_rows is missing: the rows this rollback dropped are unrecoverable';
  end if;

  select count(*) into saved from public.migration_0003_saved_rows;
  if saved <> 3 then
    raise exception 'the snapshot holds % row(s), expected 3 (one per table): refusing to finish', saved;
  end if;

  if not exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'migration_0003_saved_rows'
       and c.relrowsecurity and c.relforcerowsecurity
  ) then
    raise exception 'public.migration_0003_saved_rows is not ENABLEd + FORCEd for RLS: it holds user data and would be exposed';
  end if;

  if exists (
    select 1 from pg_policies
     where schemaname = 'public' and tablename = 'migration_0003_saved_rows'
  ) then
    raise exception 'public.migration_0003_saved_rows must have 0 policies (service key only)';
  end if;

  select string_agg(want.name, ', ')
    into leftovers
    from (values ('user_finance_settings'), ('monthly_commitments'), ('commitment_payments')) as want(name)
   where to_regclass('public.' || want.name) is not null;
  if leftovers is not null then
    raise exception 'these 0003 tables survived the rollback: %', leftovers;
  end if;

  if to_regclass('public.transaction_totals') is not null then
    raise exception 'public.transaction_totals survived the rollback';
  end if;
end $$;

commit;
