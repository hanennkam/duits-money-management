-- READ-ONLY verification after 0002_multi_user.up.sql on STAGING. Paste the result sets back. Selects only.

-- A. NULL owners (must be 0) and row counts per owner (counts only, no ids)
select count(*) as rows_total,
       count(*) filter (where user_id is null) as rows_without_owner,
       count(distinct user_id) as owners
from public.transactions;

-- B. Column definition of user_id (must be uuid, NOT NULL)
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'transactions' and column_name in ('user_id', 'image_hash', 'dedupe_hash');

-- C. Unique constraints and indexes on transactions: expect (user_id, dedupe_hash) and (user_id, image_hash)
--    partial indexes, and NO global unique on dedupe_hash alone
select indexname, indexdef from pg_indexes
where schemaname = 'public' and tablename = 'transactions'
order by indexname;

select conname, pg_get_constraintdef(oid) as definition
from pg_constraint where conrelid = 'public.transactions'::regclass;

-- D. RLS state on transactions and api_tokens (expect true)
select relname, relrowsecurity from pg_class
where oid in ('public.transactions'::regclass, 'public.api_tokens'::regclass);

-- E. Policies (expect 4 on transactions for authenticated, 3 on storage.objects, 0 on api_tokens)
select tablename, policyname, roles, cmd from pg_policies
where (schemaname = 'public' and tablename in ('transactions', 'api_tokens'))
   or (schemaname = 'storage' and tablename = 'objects')
order by tablename, policyname;

-- F. The snapshot the rollback depends on (kind and name only)
select kind, name from public.migration_0002_saved_constraints order by kind, name;
