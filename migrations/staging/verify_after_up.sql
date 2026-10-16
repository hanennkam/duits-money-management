-- READ-ONLY verification after 0002_multi_user.up.sql. Selects only: it writes nothing and names no
-- project, so the same file serves the STAGING rehearsal and the LIVE cutover.
--
-- ONE statement, ONE result grid. Read each row's `value` and compare it with the expectation written in
-- that row's own `check_name`. Anything that does not match is a stop, not a judgement call.
--
-- The two "global unique" rows are answered from the CATALOG (pg_index.indkey), not from indexdef text:
-- live carries the image_hash uniqueness as a PARTIAL unique index, whose definition does not end in
-- `(image_hash)`, so a text pattern would report "none" while the index was still there.

select ord, check_name, value
from (
  select 1 as ord, 'rows_total' as check_name,
         (select count(*)::text from public.transactions) as value
  union all
  select 2, 'rows_without_owner (expect 0)',
         (select count(*)::text from public.transactions where user_id is null)
  union all
  select 3, 'owners (expect 1)',
         (select count(distinct user_id)::text from public.transactions)
  union all
  select 4, 'user_id column (expect uuid / NO)',
         coalesce((select data_type || ' / ' || is_nullable from information_schema.columns
                    where table_schema = 'public' and table_name = 'transactions'
                      and column_name = 'user_id'), 'MISSING')
  -- No global uniqueness may survive on either column, whatever it is called and partial or not.
  union all
  select 5, 'global unique on dedupe_hash (expect none)',
         coalesce((select string_agg(ci.relname || ' :: ' || pg_get_indexdef(i.indexrelid), ' | ')
                     from pg_index i
                     join pg_class t on t.oid = i.indrelid
                     join pg_namespace n on n.oid = t.relnamespace
                     join pg_class ci on ci.oid = i.indexrelid
                    where n.nspname = 'public' and t.relname = 'transactions'
                      and i.indisunique and not i.indisprimary and i.indnkeyatts = 1
                      and (select a.attname from pg_attribute a
                            where a.attrelid = i.indrelid and a.attnum = i.indkey[0]) = 'dedupe_hash'),
                  'none')
  union all
  select 6, 'global unique on image_hash (expect none)',
         coalesce((select string_agg(ci.relname || ' :: ' || pg_get_indexdef(i.indexrelid), ' | ')
                     from pg_index i
                     join pg_class t on t.oid = i.indrelid
                     join pg_namespace n on n.oid = t.relnamespace
                     join pg_class ci on ci.oid = i.indexrelid
                    where n.nspname = 'public' and t.relname = 'transactions'
                      and i.indisunique and not i.indisprimary and i.indnkeyatts = 1
                      and (select a.attname from pg_attribute a
                            where a.attrelid = i.indrelid and a.attnum = i.indkey[0]) = 'image_hash'),
                  'none')
  -- Per-owner uniqueness: a constraint on dedupe_hash, and a PARTIAL unique index on image_hash.
  union all
  select 7, 'per-owner dedupe uniqueness (expect transactions_user_dedupe_key UNIQUE (user_id, dedupe_hash))',
         coalesce((select conname || ' ' || pg_get_constraintdef(oid) from pg_constraint
                    where conrelid = 'public.transactions'::regclass
                      and conname = 'transactions_user_dedupe_key'), 'MISSING')
  union all
  select 8, 'per-owner image uniqueness (expect transactions_user_image_uidx, WHERE image_hash IS NOT NULL)',
         coalesce((select indexdef from pg_indexes
                    where schemaname = 'public' and tablename = 'transactions'
                      and indexname = 'transactions_user_image_uidx'), 'MISSING')
  union all
  select 9, 'per-owner listing index (expect transactions_user_mode_txn_date_idx)',
         coalesce((select indexdef from pg_indexes
                    where schemaname = 'public' and tablename = 'transactions'
                      and indexname = 'transactions_user_mode_txn_date_idx'), 'MISSING')
  union all
  select 10, 'RLS on transactions / api_tokens (expect true / true)',
         (select relrowsecurity::text from pg_class where oid = 'public.transactions'::regclass)
         || ' / ' ||
         (select relrowsecurity::text from pg_class where oid = 'public.api_tokens'::regclass)
  union all
  select 11, 'policies: transactions / storage receipts / api_tokens (expect 4 / 3 / 0)',
         (select count(*)::text from pg_policies
           where schemaname = 'public' and tablename = 'transactions') || ' / ' ||
         (select count(*)::text from pg_policies
           where schemaname = 'storage' and tablename = 'objects'
             and policyname like 'receipts_owner_%') || ' / ' ||
         (select count(*)::text from pg_policies
           where schemaname = 'public' and tablename = 'api_tokens')
  union all
  select 12, 'rollback snapshot, what the down migration will restore',
         (select count(*)::text from public.migration_0002_saved_constraints) || ' row(s): ' ||
         coalesce((select string_agg(kind || ' ' || name, ' | ' order by kind, name)
                     from public.migration_0002_saved_constraints), 'none')
) checks
order by ord;
