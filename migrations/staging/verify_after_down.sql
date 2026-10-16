-- READ-ONLY verification after 0002_multi_user.down.sql on STAGING. Paste the result sets back. Selects only.

-- A. Row count must equal the count before the migration; no user_id column
select count(*) as rows_total from public.transactions;
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'transactions' and column_name = 'user_id';  -- expect no rows

-- B. Global unique constraints restored; no per-owner indexes
select indexname, indexdef from pg_indexes
where schemaname = 'public' and tablename = 'transactions' order by indexname;
select conname, pg_get_constraintdef(oid) as definition
from pg_constraint where conrelid = 'public.transactions'::regclass;

-- C. RLS state of transactions and policies (expect 0 policies, api_tokens gone)
select relname, relrowsecurity from pg_class where oid = 'public.transactions'::regclass;
select count(*) as transaction_policies from pg_policies where schemaname = 'public' and tablename = 'transactions';
select to_regclass('public.api_tokens') as api_tokens_table;
select count(*) as storage_policies from pg_policies where schemaname = 'storage' and tablename = 'objects'
  and policyname like 'receipts_owner_%';

-- D. The snapshot table is removed by the rollback (expect null)
select to_regclass('public.migration_0002_saved_constraints') as snapshot_table;
