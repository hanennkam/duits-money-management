-- 0004_commitment_link.down.sql
-- Rollback for 0004_commitment_link.up.sql. Rehearse on staging first (docs/migration-runbook.md).
--
-- It removes two things: the column public.transactions.commitment_id, and the commitment_expense output of
-- the view public.transaction_totals (by rebuilding the view to its 0003 shape). Rows: none destroyed. The
-- only "data" the rollback loses is the set of links on Pay expenses, and every one of those expenses stays
-- in the table with its amount — the balance, the month totals, the categories and the paid marks are
-- undisturbed. This is why, unlike the 0003 down file, there is no data-loss acknowledgement.
--
-- ORDER: run this file BEFORE 0003's down. 0003's down drops public.transaction_totals; running it first
-- would leave this file nothing to rebuild and no view to reshape. This file does not use 0003's snapshot.
--
-- The view is rebuilt to its 0003 shape FIRST, while the column still exists — a view (or anything
-- else with the column in its definition) holds a dependency that blocks `drop column`, so the view
-- must be replaced before the column goes. Running 0004's down on a project where the view never
-- carried `commitment_expense` is fine: the recreate below is exactly the definition that was there.
--
-- Run in ONE session.

begin;

-- 0. Nothing to roll back when NEITHER object 0004 makes exists. Anything less (only the view is
--    missing, say) is a half-applied 0004, and the file is what heals it — so it proceeds.
do $$
declare
  has_column boolean;
  has_view   boolean;
begin
  if to_regclass('public.transactions') is null then
    raise exception 'public.transactions does not exist: this migration cannot run here';
  end if;

  select exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name  = 'transactions'
       and column_name = 'commitment_id'
  ) into has_column;

  select exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name  = 'transaction_totals'
       and column_name = 'commitment_expense'
  ) into has_view;

  if not has_column and (has_view is null or not has_view) then
    raise exception 'nothing to roll back: 0004 is not applied';
  end if;
end $$;

-- 1. The view back to 0003's shape. Drop + recreate rather than CREATE OR REPLACE: a replace can never
--    REMOVE a column, and putting the old definition back requires removing one.
drop view if exists public.transaction_totals;
create or replace view public.transaction_totals with (security_invoker = true) as
  select user_id,
         mode,
         date_trunc('month', txn_date)::date as month,
         sum(amount) filter (where type = 'income')  as total_income,
         sum(amount) filter (where type = 'expense') as total_expense,
         count(*) as row_count
    from public.transactions
   group by user_id, mode, date_trunc('month', txn_date)::date;

comment on view public.transaction_totals is
  'Per owner + mode + month totals over public.transactions. The API filters user_id explicitly, like every other call.';

revoke all on public.transaction_totals from anon;
revoke all on public.transaction_totals from authenticated;
grant select on public.transaction_totals to service_role;

-- 2. The column. `if exists` because step 0 lets a healed-but-odd state through, where a view carried
--    the output column without the table ever having the link column (a project whose 0004 up stopped
--    after step 2): the column is already gone when it is reached.
alter table public.transactions drop column if exists commitment_id;

-- 3. What went must be gone: no link column anywhere, and no trace of the wider view.
do $$
begin
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name  = 'transactions'
       and column_name = 'commitment_id'
  ) then
    raise exception 'public.transactions.commitment_id survived the rollback';
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name  = 'transaction_totals'
       and column_name = 'commitment_expense'
  ) then
    raise exception 'public.transaction_totals.commitment_expense survived the rollback';
  end if;
  if not exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'transaction_totals' and c.relkind = 'v'
       and coalesce('security_invoker=true' = any(c.reloptions), false)
  ) then
    raise exception 'public.transaction_totals is missing or is not security_invoker';
  end if;
  if has_table_privilege('anon', 'public.transaction_totals', 'select') then
    raise exception 'anon has SELECT on public.transaction_totals';
  end if;
  if has_table_privilege('authenticated', 'public.transaction_totals', 'select') then
    raise exception 'authenticated has SELECT on public.transaction_totals';
  end if;
end $$;

commit;
