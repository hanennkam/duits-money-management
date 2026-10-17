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
-- It also refuses (`nothing to roll back: 0003 is not applied`) when none of the four 0003 objects exist.
-- A half-applied 0003 is a real state and it is cleaned up, snapshotting only the tables that are there.
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

-- 0a. Nothing to roll back on a project where 0003 never ran. Refusing here beats "succeeding" by writing an
--     empty snapshot of objects that never existed. A HALF-applied 0003 (some of the four objects) is a real
--     state, and this file is what cleans it up, so it proceeds and snapshots whatever is there; steps 2
--     and 3 are conditional and dynamic for exactly that case.
do $$
begin
  if to_regclass('public.user_finance_settings') is null
     and to_regclass('public.monthly_commitments') is null
     and to_regclass('public.commitment_payments') is null
     and to_regclass('public.transaction_totals') is null then
    raise exception 'nothing to roll back: 0003 is not applied';
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

-- 2. Snapshot the rows, one entry per 0003 table that EXISTS, so the shape cannot drift. A half-applied 0003
--    has fewer than three, so the inserts are dynamic (a plain `insert ... from public.x` would raise on a
--    table that is not there). The number is kept in the session setting `app.0003_tables_present` for step
--    4, which then requires exactly that many entries rather than a hard-coded 3.
do $$
declare
  name    text;
  present int := 0;
begin
  foreach name in array array['user_finance_settings', 'monthly_commitments', 'commitment_payments'] loop
    if to_regclass('public.' || name) is not null then
      execute format(
        'insert into public.migration_0003_saved_rows (table_name, payload)
           select %L, coalesce(jsonb_agg(to_jsonb(t)), ''[]''::jsonb) from public.%I t',
        name, name
      );
      present := present + 1;
    end if;
  end loop;
  perform set_config('app.0003_tables_present', present::text, false);
end $$;

-- 3. The view first (it reads public.transactions, not these tables, but it is ours to remove), then the
--    policies, then the tables. Dropping a table drops its policies, so the explicit drops only make the
--    intent readable — and they sit behind `to_regclass`, because `drop policy ... on <table>` raises when
--    the table itself is gone, which is the half-applied case above.
drop view if exists public.transaction_totals;

do $$
begin
  if to_regclass('public.user_finance_settings') is not null then
    drop policy if exists finance_settings_owner_select on public.user_finance_settings;
    drop policy if exists finance_settings_owner_insert on public.user_finance_settings;
    drop policy if exists finance_settings_owner_update on public.user_finance_settings;
    drop policy if exists finance_settings_owner_delete on public.user_finance_settings;
  end if;
  if to_regclass('public.monthly_commitments') is not null then
    drop policy if exists commitments_owner_select on public.monthly_commitments;
    drop policy if exists commitments_owner_insert on public.monthly_commitments;
    drop policy if exists commitments_owner_update on public.monthly_commitments;
    drop policy if exists commitments_owner_delete on public.monthly_commitments;
  end if;
  if to_regclass('public.commitment_payments') is not null then
    drop policy if exists commitment_payments_owner_select on public.commitment_payments;
    drop policy if exists commitment_payments_owner_insert on public.commitment_payments;
    drop policy if exists commitment_payments_owner_update on public.commitment_payments;
    drop policy if exists commitment_payments_owner_delete on public.commitment_payments;
  end if;
end $$;

drop table if exists public.commitment_payments;
drop table if exists public.monthly_commitments;
drop table if exists public.user_finance_settings;

-- 4. What went must be gone, and the snapshot must be there, complete, and closed to anon/authenticated.
do $$
declare
  saved      int;
  expected   int;
  leftovers  text;
begin
  if to_regclass('public.migration_0003_saved_rows') is null then
    raise exception 'public.migration_0003_saved_rows is missing: the rows this rollback dropped are unrecoverable';
  end if;

  if coalesce(current_setting('app.0003_tables_present', true), '') = '' then
    raise exception 'app.0003_tables_present was not set: step 2 did not run';
  end if;
  expected := current_setting('app.0003_tables_present')::int;

  select count(*) into saved from public.migration_0003_saved_rows;
  if saved <> expected then
    raise exception 'the snapshot holds % row(s), expected % (one per 0003 table that existed)', saved, expected;
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
