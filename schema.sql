-- Duits expense tracker — Phase 1 schema.
-- Run this once in the Supabase SQL editor (or `supabase db execute < schema.sql`).
--
-- NOTE (2026-10): this file still does NOT carry 0002's objects — public.transactions.user_id, the
-- per-owner unique keys (transactions_user_dedupe_key, transactions_user_image_uidx), the per-owner
-- listing index, the four row policies and public.api_tokens. A database created from this file alone is
-- a single-owner database. Syncing 0002 in here is a separate change on purpose, and it is NOT part of
-- the 0003 objects at the bottom of this file.

create table if not exists public.transactions (
  id            uuid primary key default gen_random_uuid(),
  created_at    timestamptz not null default now(),
  txn_date      date not null,
  amount        numeric(12,2) not null,
  currency      text not null default 'MYR',
  merchant      text,
  category      text,
  type          text not null default 'expense'  check (type in ('expense', 'income')),
  mode          text not null default 'personal' check (mode in ('personal', 'business')),
  items         jsonb,
  receipt_path  text,
  -- 'receipt_scan' (photo of paper, image kept) | 'bank_screenshot' (image dropped) | 'text' | 'manual'
  source        text,
  -- sha256 of the dedupe key: a bank reference, or date|amount|merchant(|ten-minute window). NULL rows
  -- are never deduped (text notes, hand-typed rows, scans with no merchant and no reference).
  dedupe_hash   text unique,
  raw_extraction jsonb,
  -- sha256 of the uploaded image bytes, so the same photo scanned twice is caught before a second Claude
  -- call. Present in the live table but missing from this file until now (schema drift, found by the
  -- audit in docs/multi-user-audit.md). NULL for text and manual rows and for bank screenshots.
  -- Its index/uniqueness is not verifiable through the API: migrations/0002 creates the per-owner
  -- unique key (user_id, image_hash), which is the one the app relies on.
  image_hash    text,
  -- Set only for an expense saved through the Pay flow (0004): the commitment the expense belongs to.
  -- Data, not a foreign key ON PURPOSE: deleting a commitment must keep every expense, and a composite
  -- FK over (commitment_id, user_id) could not support `on delete set null` beside a NOT NULL user_id.
  -- The API answers 404 for a commitment that is not the caller's, so a cross-owner link is never made.
  -- The budget bar leaves these rows out of the month's spend; the balance and month totals keep them.
  commitment_id uuid
);

comment on table public.transactions is
  'One row per extracted transaction (receipt photo, bank/e-wallet screenshot, text or manual).';

-- Storage holds paper receipts only. A bank or e-wallet screenshot is stored as its extracted fields
-- with receipt_path NULL: the screenshot is evidence of a transaction, not a document we keep.

-- Month listing and summary both filter on (mode, txn_date).
create index if not exists transactions_mode_txn_date_idx
  on public.transactions (mode, txn_date desc);

-- The API uses the service key, which bypasses RLS. RLS is on so the table stays
-- closed if an anon/publishable key ever reaches it. Add policies before exposing it.
alter table public.transactions enable row level security;

-- Storage bucket for receipt images (private; the API reads it with the service key).
insert into storage.buckets (id, name, public)
values ('receipts', 'receipts', false)
on conflict (id) do nothing;


-- ---------------------------------------------------------------------------------------------------
-- 0003: money settings, monthly commitments, per-month totals.
-- Mirrors migrations/0003_budget_commitments.up.sql, plus the object checks that file makes with `do`
-- blocks (a fresh database has no need to re-verify itself). The 0004 column on public.transactions
-- below is the one exception to "nothing here touches public.transactions" — it arrives with this file,
-- not with a run of 0004, so a database built from this file alone matches what the migrations leave.
-- ---------------------------------------------------------------------------------------------------

-- One row per user: opening balance and optional monthly budget. Balances are derived from transactions.
create table if not exists public.user_finance_settings (
  user_id         uuid primary key references auth.users(id) on delete cascade,
  opening_balance numeric(12,2) not null default 0,   -- may be negative: an overdraft is a real balance
  monthly_budget  numeric(12,2) not null default 0,   -- 0 means "no budget set"
  currency        text not null default 'MYR',        -- RM only
  updated_at      timestamptz not null default now(), -- written by the API on every write; no trigger
  constraint user_finance_settings_budget_check   check (monthly_budget >= 0),
  constraint user_finance_settings_currency_check check (currency = 'MYR')
);

comment on table public.user_finance_settings is
  'One row per user: opening balance and optional monthly budget. Balances are derived from public.transactions.';

-- Monthly commitments (rent, phone bill, ...). day_of_month is a due-date label only: nothing is
-- scheduled. `active` is the only way to say "not this month".
create table if not exists public.monthly_commitments (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  name         text not null,
  amount       numeric(12,2) not null,
  day_of_month smallint not null,
  active       boolean not null default true,
  constraint monthly_commitments_id_user_key unique (id, user_id),
  constraint monthly_commitments_name_check   check (length(btrim(name)) between 1 and 80),
  constraint monthly_commitments_amount_check check (amount > 0),
  constraint monthly_commitments_day_check    check (day_of_month between 1 and 31)
);

create index if not exists monthly_commitments_user_active_idx
  on public.monthly_commitments (user_id, active, day_of_month);

-- "Paid for YYYY-MM", one row per commitment per month: this is what stops a paid commitment from being
-- subtracted twice (the payment removes it from `unpaid`; the logged expense already counts the money).
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

-- RLS: ENABLE + FORCE (FORCE also applies the policies to the table owner; the service key has BYPASSRLS).
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

-- Per owner + mode + month totals, so an all-time balance is summed in the database (PostgREST caps a
-- response at max-rows, so summing every row in Python would truncate). security_invoker is mandatory:
-- without it the view runs as its owner and would bypass the row policies.
create or replace view public.transaction_totals with (security_invoker = true) as
  select user_id,
         mode,
         date_trunc('month', txn_date)::date as month,
         sum(amount) filter (where type = 'income')  as total_income,
         sum(amount) filter (where type = 'expense') as total_expense,
         -- The Pay-flow expense (0004): commitment_id is null on every other row. The API subtracts this
         -- from the same month's total_expense when it builds remaining_budget, and lets the balance
         -- and the month totals keep counting it.
         sum(amount) filter (where type = 'expense' and commitment_id is not null)
             as commitment_expense,
         count(*) as row_count
    from public.transactions
   -- The cast is repeated in the GROUP BY on purpose: Postgres matches a grouped expression by its shape,
   -- so a bare `date_trunc(...)` here with `date_trunc(...)::date` in the select list is rejected.
   group by user_id, mode, date_trunc('month', txn_date)::date;

comment on view public.transaction_totals is
  'Per owner + mode + month totals over public.transactions. The API filters user_id explicitly, like every other call.';

-- The view has no policy of its own, so these grants are the whole gate. The API is the only reader.
revoke all on public.transaction_totals from anon;
revoke all on public.transaction_totals from authenticated;
grant select on public.transaction_totals to service_role;
