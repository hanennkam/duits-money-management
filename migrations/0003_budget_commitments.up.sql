-- 0003_budget_commitments.up.sql
-- NOT EXECUTED on live. Rehearse on a staging Supabase project first (docs/migration-runbook.md).
-- New objects only: there is no backfill, so unlike 0002 nothing here needs `app.owner_id`.
-- Run in ONE session (the Supabase SQL editor runs a script in one session). Every step either does what
-- it says or raises: a silent no-op is a failed migration, so the guards at the end name what is missing.
--
-- 0003 touches NOTHING in public.transactions: no column added, no row changed. `txn_date` is a plain
-- `date` (schema.sql), so the view below has no timezone in it and cannot disagree with the API's
-- `db.month_bounds()`, which builds `datetime.date` bounds and compares them as ISO strings.

begin;

-- 1. Per-user money settings. One row per user; `primary key (user_id)` is what makes it one row.
create table if not exists public.user_finance_settings (
  user_id         uuid primary key references auth.users(id) on delete cascade,
  opening_balance numeric(12,2) not null default 0,   -- may be negative: an overdraft is a real balance
  monthly_budget  numeric(12,2) not null default 0,   -- 0 means "no budget set", so no budget row is shown
  currency        text not null default 'MYR',        -- RM only
  updated_at      timestamptz not null default now(), -- written by the API on every write; no trigger
  constraint user_finance_settings_budget_check   check (monthly_budget >= 0),
  constraint user_finance_settings_currency_check check (currency = 'MYR')
);

comment on table public.user_finance_settings is
  'One row per user: opening balance and optional monthly budget. Balances are derived from public.transactions.';

-- 2. Monthly commitments (rent, phone bill, ...). `day_of_month` is a due-date label only: nothing is
--    scheduled, and 31 in a 30-day month simply reads as "the 31st". `active` is the ONLY way to say
--    "not this month" (case 2: no per-month skip).
create table if not exists public.monthly_commitments (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  name         text not null,
  amount       numeric(12,2) not null,
  day_of_month smallint not null,
  active       boolean not null default true,
  -- The target of commitment_payments' composite FK: it makes "a payment may only point at a
  -- commitment of the same owner" a database rule, not just an application one.
  constraint monthly_commitments_id_user_key unique (id, user_id),
  constraint monthly_commitments_name_check   check (length(btrim(name)) between 1 and 80),
  constraint monthly_commitments_amount_check check (amount > 0),
  constraint monthly_commitments_day_check    check (day_of_month between 1 and 31)
);

create index if not exists monthly_commitments_user_active_idx
  on public.monthly_commitments (user_id, active, day_of_month);

-- 3. "Paid for YYYY-MM", one row per commitment per month. This is what stops a paid commitment from
--    being subtracted twice: the payment row removes it from `unpaid`, while the transaction the user
--    logged when paying it is already an expense in the month's totals.
create table if not exists public.commitment_payments (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  commitment_id uuid not null,
  month         text not null,
  paid_at       timestamptz not null default now(),
  constraint commitment_payments_month_check check (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  constraint commitment_payments_unique      unique (commitment_id, month),
  constraint commitment_payments_commitment_owner_fkey
    foreign key (commitment_id, user_id)
    references public.monthly_commitments (id, user_id) on delete cascade
);

-- 4. Row-level security. The API uses the service key, which bypasses RLS, so these policies are the
--    backstop for any other key or any direct client access. ENABLE + FORCE: 0002 uses ENABLE only, so
--    FORCE is a deliberate step further for these tables (FORCE also applies the policies to the table
--    owner). It is harmless for a role that bypasses RLS — Supabase's `service_role` has BYPASSRLS and
--    the SQL editor's `postgres` is a superuser — and migrations/staging/verify_after_0003.sql plus the
--    staging isolation suite are what prove the API path still works with it on.
alter table public.user_finance_settings enable row level security;
alter table public.user_finance_settings force  row level security;
create policy finance_settings_owner_select on public.user_finance_settings
  for select to authenticated using (user_id = auth.uid());
create policy finance_settings_owner_insert on public.user_finance_settings
  for insert to authenticated with check (user_id = auth.uid());
create policy finance_settings_owner_update on public.user_finance_settings
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy finance_settings_owner_delete on public.user_finance_settings
  for delete to authenticated using (user_id = auth.uid());

alter table public.monthly_commitments enable row level security;
alter table public.monthly_commitments force  row level security;
create policy commitments_owner_select on public.monthly_commitments
  for select to authenticated using (user_id = auth.uid());
create policy commitments_owner_insert on public.monthly_commitments
  for insert to authenticated with check (user_id = auth.uid());
create policy commitments_owner_update on public.monthly_commitments
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy commitments_owner_delete on public.monthly_commitments
  for delete to authenticated using (user_id = auth.uid());

alter table public.commitment_payments enable row level security;
alter table public.commitment_payments force  row level security;
create policy commitment_payments_owner_select on public.commitment_payments
  for select to authenticated using (user_id = auth.uid());
create policy commitment_payments_owner_insert on public.commitment_payments
  for insert to authenticated with check (user_id = auth.uid());
create policy commitment_payments_owner_update on public.commitment_payments
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy commitment_payments_owner_delete on public.commitment_payments
  for delete to authenticated using (user_id = auth.uid());

-- 5. Per owner + mode + month totals over public.transactions, so an all-time balance is summed in the
--    database. PostgREST caps a response (max-rows, 1000 by default), so summing every row in Python
--    would silently truncate once a household has enough history; this returns a handful of rows.
--    `security_invoker = true` (Postgres 15+) is MANDATORY: without it the view runs as its owner and
--    would bypass the row policies for an authenticated client.
create or replace view public.transaction_totals with (security_invoker = true) as
  select user_id,
         mode,
         date_trunc('month', txn_date)::date as month,
         sum(amount) filter (where type = 'income')  as total_income,
         sum(amount) filter (where type = 'expense') as total_expense,
         count(*) as row_count
    from public.transactions
   -- The cast is repeated in the GROUP BY on purpose: Postgres matches a grouped expression by its shape,
   -- so a bare `date_trunc(...)` here with `date_trunc(...)::date` in the select list is rejected.
   group by user_id, mode, date_trunc('month', txn_date)::date;

comment on view public.transaction_totals is
  'Per owner + mode + month totals over public.transactions. The API filters user_id explicitly, like every other call.';

-- The view carries no row policy of its own, so the grant is the whole gate for anyone who is not the
-- service key. The API is the only reader (app/db.py, service key), and the page never calls PostgREST.
revoke all on public.transaction_totals from anon;
revoke all on public.transaction_totals from authenticated;
grant select on public.transaction_totals to service_role;

-- 6. Everything above either did what it says or raises. A missing table, a table that already existed
--    with another shape (which `if not exists` would have skipped in silence), a missing policy or an
--    exposed view all fail here by name.
do $$
declare
  missing text;
begin
  select string_agg(t.name, ', ')
    into missing
    from (values ('user_finance_settings'), ('monthly_commitments'), ('commitment_payments')) as t(name)
   where not exists (
     select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = t.name
        and c.relrowsecurity and c.relforcerowsecurity
   );
  if missing is not null then
    raise exception 'RLS is not ENABLEd + FORCEd on: %', missing;
  end if;

  select string_agg(want.table_name || '.' || want.constraint_name, ', ')
    into missing
    from (values
      ('user_finance_settings', 'user_finance_settings_budget_check'),
      ('user_finance_settings', 'user_finance_settings_currency_check'),
      ('monthly_commitments', 'monthly_commitments_id_user_key'),
      ('monthly_commitments', 'monthly_commitments_name_check'),
      ('monthly_commitments', 'monthly_commitments_amount_check'),
      ('monthly_commitments', 'monthly_commitments_day_check'),
      ('commitment_payments', 'commitment_payments_month_check'),
      ('commitment_payments', 'commitment_payments_unique'),
      ('commitment_payments', 'commitment_payments_commitment_owner_fkey')
    ) as want(table_name, constraint_name)
   where not exists (
     select 1 from pg_constraint k
       join pg_class c on c.oid = k.conrelid
       join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public' and c.relname = want.table_name
        and k.conname = want.constraint_name
   );
  if missing is not null then
    raise exception 'expected constraint(s) missing: %', missing;
  end if;

  -- The composite FK must name BOTH columns, or it does not pin the owner.
  if not exists (
    select 1 from pg_constraint k
      join pg_class c on c.oid = k.conrelid
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'commitment_payments'
       and k.conname = 'commitment_payments_commitment_owner_fkey'
       and pg_get_constraintdef(k.oid) like 'FOREIGN KEY (commitment_id, user_id)%'
  ) then
    raise exception 'commitment_payments_commitment_owner_fkey does not cover (commitment_id, user_id)';
  end if;

  select string_agg(t.name || '=' || t.cnt, ', ')
    into missing
    from (
      select c.relname as name, count(p.oid) as cnt
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace and n.nspname = 'public'
        left join pg_policy p on p.polrelid = c.oid
       where c.relname in ('user_finance_settings', 'monthly_commitments', 'commitment_payments')
       group by c.relname
    ) as t
   where t.cnt <> 4;
  if missing is not null then
    raise exception 'expected 4 policies per new table, got: %', missing;
  end if;

  if not exists (
    select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relname = 'transaction_totals' and c.relkind = 'v'
       and coalesce('security_invoker=true' = any(c.reloptions), false)
  ) then
    raise exception 'public.transaction_totals is missing or is not security_invoker';
  end if;

  if has_table_privilege('anon', 'public.transaction_totals', 'select') then
    raise exception 'anon still has SELECT on public.transaction_totals';
  end if;
  if has_table_privilege('authenticated', 'public.transaction_totals', 'select') then
    raise exception 'authenticated still has SELECT on public.transaction_totals';
  end if;
end $$;

commit;
