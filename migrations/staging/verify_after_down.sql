-- READ-ONLY verification after 0002_multi_user.down.sql. Selects only: it writes nothing and names no
-- project, so the same file serves the STAGING rehearsal and a LIVE rollback.
--
-- ONE statement, ONE result grid. Read each row's `value` and compare it with the expectation written in
-- that row's own `check_name`. The point of the rollback is that the table's uniqueness is back EXACTLY as
-- the up migration found it, so rows 3 and 4 print the restored definitions verbatim: whatever the original
-- object was — a constraint or an index, partial or not — it must come back in that same form.

select ord, check_name, value
from (
  select 1 as ord, 'rows_total (expect the count from before the migration)' as check_name,
         (select count(*)::text from public.transactions) as value
  union all
  select 2, 'user_id column (expect MISSING)',
         coalesce((select data_type from information_schema.columns
                    where table_schema = 'public' and table_name = 'transactions'
                      and column_name = 'user_id'), 'MISSING')
  -- Everything restored on the two columns: name, object kind, and the definition verbatim.
  union all
  select 3, 'restored dedupe uniqueness (expect: constraint transactions_dedupe_hash_key :: UNIQUE (dedupe_hash))',
         coalesce((select string_agg(ci.relname
                      || ' [' || case when c.oid is null then 'index' else 'constraint' end || '] :: '
                      || case when c.oid is null then pg_get_indexdef(i.indexrelid)
                              else pg_get_constraintdef(c.oid) end, ' | ' order by ci.relname)
                     from pg_index i
                     join pg_class t on t.oid = i.indrelid
                     join pg_namespace n on n.oid = t.relnamespace
                     join pg_class ci on ci.oid = i.indexrelid
                     left join pg_constraint c on c.conindid = i.indexrelid
                    where n.nspname = 'public' and t.relname = 'transactions'
                      and i.indisunique and not i.indisprimary and i.indnkeyatts = 1
                      and (select a.attname from pg_attribute a
                            where a.attrelid = i.indrelid and a.attnum = i.indkey[0]) = 'dedupe_hash'),
                  'MISSING')
  union all
  select 4, 'restored image uniqueness (expect: index transactions_image_hash_uidx :: ... WHERE (image_hash IS NOT NULL))',
         coalesce((select string_agg(ci.relname
                      || ' [' || case when c.oid is null then 'index' else 'constraint' end || '] :: '
                      || case when c.oid is null then pg_get_indexdef(i.indexrelid)
                              else pg_get_constraintdef(c.oid) end, ' | ' order by ci.relname)
                     from pg_index i
                     join pg_class t on t.oid = i.indrelid
                     join pg_namespace n on n.oid = t.relnamespace
                     join pg_class ci on ci.oid = i.indexrelid
                     left join pg_constraint c on c.conindid = i.indexrelid
                    where n.nspname = 'public' and t.relname = 'transactions'
                      and i.indisunique and not i.indisprimary and i.indnkeyatts = 1
                      and (select a.attname from pg_attribute a
                            where a.attrelid = i.indrelid and a.attnum = i.indkey[0]) = 'image_hash'),
                  'MISSING')
  -- No trace of the per-owner shape may be left.
  union all
  select 5, 'per-owner objects left behind (expect 0)',
         (select count(*)::text from pg_indexes
           where schemaname = 'public' and tablename = 'transactions'
             and indexname like 'transactions_user_%')
  union all
  select 6, 'RLS on transactions (expect true: schema.sql sets it)',
         (select relrowsecurity::text from pg_class where oid = 'public.transactions'::regclass)
  union all
  select 7, 'policies: transactions / storage receipts (expect 0 / 0)',
         (select count(*)::text from pg_policies
           where schemaname = 'public' and tablename = 'transactions') || ' / ' ||
         (select count(*)::text from pg_policies
           where schemaname = 'storage' and tablename = 'objects'
             and policyname like 'receipts_owner_%')
  union all
  select 8, 'api_tokens table (expect MISSING)',
         coalesce(to_regclass('public.api_tokens')::text, 'MISSING')
  union all
  select 9, 'rollback snapshot table (expect MISSING)',
         coalesce(to_regclass('public.migration_0002_saved_constraints')::text, 'MISSING')
) checks
order by ord;
