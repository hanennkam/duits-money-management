-- STAGING ONLY. Builds the pre-migration schema as the audit found it:
--   schema.sql, plus the image_hash column that is live but missing from schema.sql.
-- Run once in the STAGING project's SQL editor, on an empty staging project.
-- Never run this against the live project.

-- ---- schema.sql (verbatim) -------------------------------------------------------------------
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

create index if not exists transactions_mode_txn_date_idx
  on public.transactions (mode, txn_date desc);

alter table public.transactions enable row level security;

insert into storage.buckets (id, name, public)
values ('receipts', 'receipts', false)
on conflict (id) do nothing;

-- ---- live-only shapes, found by the audit and confirmed in the live SQL editor ---------------------
-- `image_hash` is live but absent from schema.sql, and live carries its uniqueness as a PARTIAL UNIQUE
-- INDEX rather than a constraint. Staging is rebuilt with that exact shape, so the migration is rehearsed
-- against what live actually has — a text pattern ending in `(image_hash)` does not match a partial index,
-- which is exactly the gap this rebuild closes.
alter table public.transactions add column if not exists image_hash text;

create unique index if not exists transactions_image_hash_uidx
  on public.transactions (image_hash) where image_hash is not null;
