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
  image_hash    text
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
