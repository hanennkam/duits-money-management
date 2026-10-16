-- Read-only audit queries for the live Supabase project. Run these in the SQL editor yourself.
-- Every statement is a SELECT. None of them change anything.
-- They return catalog structure only (names, types, flags). Do not paste any row data back.

-- A. Columns, types and defaults (precision of amount, defaults of type/mode/currency)
select column_name, data_type, character_maximum_length, numeric_precision, numeric_scale,
       is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'transactions'
order by ordinal_position;

-- B. Every index and unique/primary constraint on transactions (is dedupe_hash unique? is image_hash?)
select indexname, indexdef from pg_indexes
where schemaname = 'public' and tablename = 'transactions';

select conname, contype, pg_get_constraintdef(oid) as definition
from pg_constraint
where conrelid = 'public.transactions'::regclass;

-- C. Row-level security state on transactions (relrowsecurity = RLS enabled, relforcerowsecurity = forced)
select relname, relrowsecurity, relforcerowsecurity
from pg_class
where oid = 'public.transactions'::regclass;

-- D. Policies on transactions (expected: none today, since RLS only blocks the anon/authenticated roles)
select policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public' and tablename = 'transactions';

-- E. Storage: bucket settings, and policies on storage.objects that mention the receipts bucket
select id, name, public, file_size_limit, allowed_mime_types
from storage.buckets;

select policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'storage' and tablename = 'objects';

-- F. Triggers and functions in public (anything that writes on insert/update matters for step 2)
select tgname, tgenabled from pg_trigger
where tgrelid = 'public.transactions'::regclass and not tgisinternal;

select proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where n.nspname = 'public';

-- G. Grants on transactions for the client roles (anon / authenticated should have none after RLS)
select grantee, privilege_type from information_schema.role_table_grants
where table_schema = 'public' and table_name = 'transactions' and grantee in ('anon', 'authenticated');
