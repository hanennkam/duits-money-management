-- 0004_commitment_link.up.sql
-- NOT EXECUTED by the assistant. Run it in the Supabase SQL editor of STAGING first (after a backup),
-- then the same file on live, before the code that reads these objects is deployed.
--
-- One nullable link column on public.transactions: `commitment_id`, set only for an expense the Add
-- sheet saved through a commitment's Pay button. It is what lets the budget bar leave a paid bill out
-- of the month's spend while the balance and the month cards keep counting that same expense.
--
-- REQUIRES 0003 applied: step 2 replaces the `public.transaction_totals` view 0003 created. The file
-- raises on a project that is still pre-0003 instead of failing later on the view.
--
-- No foreign key ON PURPOSE. An FK would either cascade (deleting a commitment must never take an
-- expense with it) or force `on delete set null` onto `user_id` beside `commitment_id` (a composite FK
-- over (commitment_id, user_id), however 0003's payments link is shaped, and `user_id` is NOT NULL).
-- Ownership of the id is therefore checked by the API instead (app/main.py POST /transactions): a
-- commitment that is not the caller's answers 404, so a cross-owner link cannot be created; a soft
-- column never endangers a row's history. This mirrors how `dedupe_hash` and `image_hash` are data the
-- API polices, not the database.
--
-- No backfill: past Pay rows cannot be identified after the fact (they carry the same shape as any
-- "bills" expense), so they stay linked only as far as their paid marks say. Nothing is added, nothing
-- is rewritten: 0004 is a column, a nullable link, and a wider view — which is why the down file needs
-- no data-loss acknowledgement.
--
-- Run in ONE session. Every step either does what it says or raises: a silent no-op is a failed
-- migration, so the guards at the end name what is missing.

begin;

-- 0. Guard: 0004 is built ON 0003. It replaces 0003's view and links transactions to 0003's
--    commitments, so both must already exist. Read-only checks; nothing is created here.
do $$
begin
  if to_regclass('public.transaction_totals') is null then
    raise exception 'run 0003 first: public.transaction_totals is missing';
  end if;
  if to_regclass('public.monthly_commitments') is null then
    raise exception 'run 0003 first: public.monthly_commitments is missing';
  end if;
  if exists (
    select 1 from information_schema.tables
     where table_schema = 'public' and table_name = 'transactions'
  ) = false then
    raise exception 'public.transactions does not exist: this migration cannot run here';
  end if;
end $$;

-- 1. The link column. Nullable: every row that is not from the Pay flow stays null forever, and the
--    view's filter reads a null as "not a Pay expense", exactly like a row that could not carry one.
alter table public.transactions add column if not exists commitment_id uuid;

comment on column public.transactions.commitment_id is
  'Set only for an expense saved through the Pay flow (0004): the commitment the expense belongs to. '
  'Data, not a foreign key — deleting a commitment must keep every expense. The API refuses an id that '
  'is not the caller''s own commitment.';

-- 2. The view, rebuilt with one extra column. CREATE OR REPLACE appends the column (Postgres allows a
--    replace that only adds columns at the end), so a half-ridden project is not a problem — and a
--    re-run is idempotent. `commitment_expense` is the slice of `total_expense` that came from the Pay
--    flow: the API subtracts it from the same month's `total_expense` when it builds `remaining_budget`,
--    and never lets it touch the balance or the month totals.
create or replace view public.transaction_totals with (security_invoker = true) as
  select user_id,
         mode,
         date_trunc('month', txn_date)::date as month,
         sum(amount) filter (where type = 'income')  as total_income,
         sum(amount) filter (where type = 'expense') as total_expense,
         count(*) as row_count,
         -- LAST on purpose: CREATE OR REPLACE VIEW may only append columns, and 0003 ends with row_count.
         sum(amount) filter (where type = 'expense' and commitment_id is not null)
             as commitment_expense
    from public.transactions
   -- The cast is repeated in the GROUP BY on purpose, as in 0003: Postgres matches a grouped expression
   -- by its shape, so a bare `date_trunc(...)` here with `date_trunc(...)::date` in the select list is
   -- rejected.
   group by user_id, mode, date_trunc('month', txn_date)::date;

comment on view public.transaction_totals is
  'Per owner + mode + month totals over public.transactions, with the Pay-flow expense split out '
  '(commitment_expense). The API filters user_id explicitly, like every other call.';

-- The grants persist across CREATE OR REPLACE, but restating them keeps the file self-sufficient: the
-- API is still the only reader of the view (app/db.py, service key).
revoke all on public.transaction_totals from anon;
revoke all on public.transaction_totals from authenticated;
grant select on public.transaction_totals to service_role;

-- 3. Everything above either did what it says or raises. A missing column, a view without the new
--    output column, a security_invoker that went away, or an exposed pass-through all fail here by name.
do $$
declare
  missing text;
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'transactions' and column_name = 'commitment_id'
  ) then
    raise exception 'public.transactions.commitment_id is missing: step 1 did not run';
  end if;

  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public'
       and table_name  = 'transaction_totals'
       and column_name = 'commitment_expense'
  ) then
    raise exception 'public.transaction_totals has no commitment_expense column: step 2 did not run';
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
  if not has_table_privilege('service_role', 'public.transaction_totals', 'select') then
    raise exception 'service_role lost SELECT on public.transaction_totals';
  end if;

  -- Nothing else was meant to change: every policy, constraint and index of 0002/0003 is left alone,
  -- so there is no RLS/constraint count to re-check here. The column is deliberately NOT unique,
  -- NOT enforced and NOT a foreign key — see the header for why that is the design and not a shortcut.
end $$;

commit;
