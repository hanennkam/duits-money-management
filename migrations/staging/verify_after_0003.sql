-- READ-ONLY verification after 0003_budget_commitments.up.sql. Selects only: it writes nothing and names
-- no project, so the same file serves the STAGING rehearsal and any later live run.
--
-- ONE statement, ONE result grid. Read each row's `value` and compare it with the expectation written in
-- that row's own `check_name`. Anything that does not match is a stop, not a judgement call.
--
-- RLS is checked as BOTH relrowsecurity AND relforcerowsecurity: 0003 uses FORCE (0002 used ENABLE only),
-- and a `false` in either half means the backstop is not what this migration promised.
-- The view's privileges are checked with has_table_privilege, because the view has no policy of its own:
-- its grants are the entire gate for anyone who is not the service key.

select ord, check_name, value
from (
  select 1 as ord, 'user_finance_settings columns (expect user_id uuid/NO, opening_balance numeric/NO, monthly_budget numeric/NO, currency text/NO, updated_at timestamptz/NO)' as check_name,
         coalesce((select string_agg(column_name || ' ' || data_type || '/' || is_nullable, ', ' order by ordinal_position)
                     from information_schema.columns
                    where table_schema = 'public' and table_name = 'user_finance_settings'), 'MISSING') as value
  union all
  select 2, 'monthly_commitments columns (expect id uuid/NO, user_id uuid/NO, created_at timestamptz/NO, name text/NO, amount numeric/NO, day_of_month smallint/NO, active boolean/NO)',
         coalesce((select string_agg(column_name || ' ' || data_type || '/' || is_nullable, ', ' order by ordinal_position)
                     from information_schema.columns
                    where table_schema = 'public' and table_name = 'monthly_commitments'), 'MISSING')
  union all
  select 3, 'commitment_payments columns (expect id uuid/NO, user_id uuid/NO, commitment_id uuid/NO, month text/NO, paid_at timestamptz/NO)',
         coalesce((select string_agg(column_name || ' ' || data_type || '/' || is_nullable, ', ' order by ordinal_position)
                     from information_schema.columns
                    where table_schema = 'public' and table_name = 'commitment_payments'), 'MISSING')
  -- ENABLE + FORCE on all three (each half, per table).
  union all
  select 4, 'RLS enabled / forced: settings, commitments, payments (expect true/true, true/true, true/true)',
         (select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
           where c.oid = to_regclass('public.user_finance_settings'))
         || ', ' ||
         (select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
           where c.oid = to_regclass('public.monthly_commitments'))
         || ', ' ||
         (select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
           where c.oid = to_regclass('public.commitment_payments'))
  union all
  select 5, 'policies: settings / commitments / payments (expect 4 / 4 / 4)',
         (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'user_finance_settings') || ' / ' ||
         (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'monthly_commitments') || ' / ' ||
         (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'commitment_payments')
  union all
  select 6, 'insert/update policies carrying a WITH CHECK (expect 6: insert and update on each of the 3 tables)',
         (select count(*)::text from pg_policies
           where schemaname = 'public'
             and tablename in ('user_finance_settings', 'monthly_commitments', 'commitment_payments')
             and with_check is not null)
  -- The composite FK is what pins the owner: it must cover BOTH columns.
  union all
  select 7, 'commitment_payments composite FK (expect FOREIGN KEY (commitment_id, user_id) REFERENCES monthly_commitments(id, user_id) ON DELETE CASCADE)',
         coalesce((select pg_get_constraintdef(oid) from pg_constraint
                    where conrelid = to_regclass('public.commitment_payments')
                      and conname = 'commitment_payments_commitment_owner_fkey'), 'MISSING')
  union all
  select 8, 'commitment_payments month + one-payment-per-month (expect the regex check and unique (commitment_id, month))',
         coalesce((select string_agg(conname || ': ' || pg_get_constraintdef(oid), ' | ' order by conname)
                     from pg_constraint
                    where conrelid = to_regclass('public.commitment_payments') and contype = 'c'), 'MISSING') || ' ; ' ||
         coalesce((select pg_get_constraintdef(oid) from pg_constraint
                    where conrelid = to_regclass('public.commitment_payments')
                      and conname = 'commitment_payments_unique'), 'MISSING')
  union all
  select 9, 'amount > 0 and day_of_month 1-31 on monthly_commitments (expect both present)',
         coalesce((select string_agg(conname || ': ' || pg_get_constraintdef(oid), ' | ' order by conname)
                     from pg_constraint
                    where conrelid = to_regclass('public.monthly_commitments') and contype = 'c'), 'MISSING')
  union all
  select 10, 'FK target monthly_commitments(id, user_id) (expect UNIQUE (id, user_id))',
         coalesce((select pg_get_constraintdef(oid) from pg_constraint
                    where conrelid = to_regclass('public.monthly_commitments')
                      and conname = 'monthly_commitments_id_user_key'), 'MISSING')
  union all
  select 11, 'listing index (expect monthly_commitments_user_active_idx)',
         coalesce((select indexdef from pg_indexes
                    where schemaname = 'public' and tablename = 'monthly_commitments'
                      and indexname = 'monthly_commitments_user_active_idx'), 'MISSING')
  union all
  select 12, 'transaction_totals is a view and security_invoker (expect v / true)',
         coalesce((select c.relkind::text || ' / ' || coalesce(('security_invoker=true' = any(c.reloptions))::text, 'false')
                     from pg_class c join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public' and c.relname = 'transaction_totals'), 'MISSING')
  -- The view has no policy, so its grants are the gate. Both must be false.
  union all
  select 13, 'SELECT privilege on transaction_totals for anon / authenticated (expect false / false)',
         has_table_privilege('anon', 'public.transaction_totals', 'select')::text || ' / ' ||
         has_table_privilege('authenticated', 'public.transaction_totals', 'select')::text
  union all
  select 14, 'transaction_totals definition',
         coalesce((select pg_get_viewdef('public.transaction_totals'::regclass, true)), 'MISSING')
  union all
  select 15, 'row counts: settings / commitments / payments (real data after a rehearsal; 0 on an empty project)',
         (select count(*)::text from public.user_finance_settings) || ' / ' ||
         (select count(*)::text from public.monthly_commitments) || ' / ' ||
         (select count(*)::text from public.commitment_payments)
  union all
  select 16, 'transactions rows (0003 must not change this; compare with the count before the run)',
         (select count(*)::text from public.transactions)
  -- Present only after a rollback; it must be RLS-protected and hold 3 snapshot rows.
  union all
  select 17, 'rollback snapshot (expect absent, or 3 row(s) with RLS enabled+forced and 0 policies)',
         case
           when to_regclass('public.migration_0003_saved_rows') is null then 'absent'
           else (select count(*)::text from public.migration_0003_saved_rows) || ' row(s), rls ' ||
                (select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
                  where c.oid = to_regclass('public.migration_0003_saved_rows')) || ', policies ' ||
                (select count(*)::text from pg_policies
                  where schemaname = 'public' and tablename = 'migration_0003_saved_rows')
         end
) checks
order by ord;
