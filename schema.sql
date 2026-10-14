-- Duits expense tracker — Phase 1 schema.
-- Run this once in the Supabase SQL editor (or `supabase db execute < schema.sql`).

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
  source        text,
  dedupe_hash   text unique,
  raw_extraction jsonb
);

comment on table public.transactions is 'One row per extracted transaction (receipt scan, text or manual).';

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
