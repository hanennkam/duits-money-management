-- READ-ONLY verification after 0003_budget_commitments.up.sql. Selects only: it writes nothing and names
-- no project, so the same file serves the STAGING rehearsal and any later live run.
--
-- ONE statement, ONE result grid. Read each row's `value` and compare it with the expectation written in
-- that row's own `check_name`. Anything that does not match is a stop, not a judgement call.
--
-- Row 0 is the prerequisite and comes first on purpose: 0003's view reads `public.transactions.user_id`,
-- which 0002 adds, so a pre-0002 project reads `MISSING (0002 is not applied: ...)` there and MISSING
-- everywhere below it.
--
-- RLS is checked as BOTH relrowsecurity AND relforcerowsecurity: 0003 uses FORCE (0002 used ENABLE only),
-- and a `false` in either half means the backstop is not what this migration promised.
-- The view's privileges are checked with has_table_privilege, because the view has no policy of its own:
-- its grants are the entire gate for anyone who is not the service key.
--
-- Every object this file must be able to REPORT as MISSING is named only inside a STRING — `to_regclass(...)`,
-- or `query_to_xml(...)` — and never in code position. Postgres resolves a relation name while it PARSES the
-- statement, before any `case` or guard is evaluated, so a direct `from public.<missing>` raises 42P01 instead
-- of printing MISSING. That is not hypothetical: it is what rows 15 and 17 did on staging (2026-10-18) —
-- `public.migration_0003_saved_rows` is created by the 0003 DOWN file, so it is absent in the normal post-`up`
-- state, and the three 0003 tables are absent pre-0003 and again after a rollback, which is exactly when this
-- grid is meant to answer (docs/migration-runbook.md §10 steps 2 and 5).

select ord, check_name, value
from (
  -- Prerequisite first, as `ord 0` so every other row keeps its number: step 5's view reads
  -- public.transactions.user_id, which 0002 adds. On a pre-0002 project every later row reads MISSING, and
  -- this one says why. It is also the row that must still read `uuid / NO` after a 0003 rollback.
  select 0 as ord, 'transactions.user_id from 0002 (expect uuid / NO; MISSING means run migrations/0002_multi_user.up.sql first)' as check_name,
         coalesce((select c.data_type || ' / ' || c.is_nullable from information_schema.columns c
                    where c.table_schema = 'public' and c.table_name = 'transactions' and c.column_name = 'user_id'),
                  'MISSING (0002 is not applied: public.transactions.user_id does not exist)') as value
  union all
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
  -- ENABLE + FORCE on all three (each half, per table). A missing table reads MISSING, not NULL.
  union all
  select 4, 'RLS enabled / forced: settings, commitments, payments (expect true/true, true/true, true/true)',
         coalesce((select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
                    where c.oid = to_regclass('public.user_finance_settings')), 'MISSING')
         || ', ' ||
         coalesce((select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
                    where c.oid = to_regclass('public.monthly_commitments')), 'MISSING')
         || ', ' ||
         coalesce((select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
                    where c.oid = to_regclass('public.commitment_payments')), 'MISSING')
  union all
  select 5, 'policies: settings / commitments / payments (expect 4 / 4 / 4)',
         case when to_regclass('public.user_finance_settings') is null
                or to_regclass('public.monthly_commitments') is null
                or to_regclass('public.commitment_payments') is null
              then 'MISSING (a 0003 table is gone, so it has no policies either)'
              else (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'user_finance_settings') || ' / ' ||
                   (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'monthly_commitments') || ' / ' ||
                   (select count(*)::text from pg_policies where schemaname = 'public' and tablename = 'commitment_payments')
         end
  union all
  select 6, 'insert/update policies carrying a WITH CHECK (expect 6: insert and update on each of the 3 tables)',
         case when to_regclass('public.user_finance_settings') is null
                or to_regclass('public.monthly_commitments') is null
                or to_regclass('public.commitment_payments') is null
              then 'MISSING (a 0003 table is gone, so it has no policies either)'
              else (select count(*)::text from pg_policies
                     where schemaname = 'public'
                       and tablename in ('user_finance_settings', 'monthly_commitments', 'commitment_payments')
                       and with_check is not null)
         end
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
  -- The view has no policy, so its grants are the gate. Both must be false. A missing view reads MISSING:
  -- has_table_privilege on a relation that is not there raises, which would break the post-rollback run.
  union all
  select 13, 'SELECT privilege on transaction_totals for anon / authenticated (expect false / false)',
         case when to_regclass('public.transaction_totals') is null
              then 'MISSING (no view, so no grants to report)'
              else has_table_privilege('anon', 'public.transaction_totals', 'select')::text || ' / ' ||
                   has_table_privilege('authenticated', 'public.transaction_totals', 'select')::text
         end
  union all
  select 14, 'transaction_totals definition',
         case when to_regclass('public.transaction_totals') is null
              then 'MISSING'
              else pg_get_viewdef(to_regclass('public.transaction_totals'), true)
         end
  union all
  -- The three counts are read through query_to_xml, not `from public.xxx`: a relation named in code position is
  -- resolved at parse time, so the branch below would raise 42P01 on a project where 0003 is not applied —
  -- exactly the state this row exists to report. `to_regclass` still guards the branch, and query_to_xml reads
  -- its query only when the branch runs. (Same idiom as row 17.)
  --
  -- `//c/text()` rather than the more common `/row/c/text()`: both match these calls, but `//c` is a descendant
  -- search, so it does not depend on which wrapper element `tableforest` selects. And the coalesce is not
  -- decoration: if the read ever came back empty the cell would print NULL, and a blank cell reads like a pass.
  select 15, 'row counts: settings / commitments / payments (real data after a rehearsal; 0 on an empty project)',
         case when to_regclass('public.user_finance_settings') is null
                or to_regclass('public.monthly_commitments') is null
                or to_regclass('public.commitment_payments') is null
              then 'MISSING (0003 is not applied, so it holds no rows)'
              else coalesce((xpath('//c/text()', query_to_xml(
                     'select count(*) as c from public.user_finance_settings', false, true, '')))[1]::text,
                     'UNREADABLE') || ' / ' ||
                   coalesce((xpath('//c/text()', query_to_xml(
                     'select count(*) as c from public.monthly_commitments', false, true, '')))[1]::text,
                     'UNREADABLE') || ' / ' ||
                   coalesce((xpath('//c/text()', query_to_xml(
                     'select count(*) as c from public.commitment_payments', false, true, '')))[1]::text,
                     'UNREADABLE')
         end
  union all
  select 16, 'transactions rows (0003 must not change this; compare with the count before the run)',
         (select count(*)::text from public.transactions)
  -- Present only after a rollback; it must be RLS-protected and hold 3 snapshot rows. The count is read through
  -- query_to_xml: that table is created by the 0003 DOWN file, so in the normal post-`up` state it does not
  -- exist, and a direct `from public.migration_0003_saved_rows` raises 42P01 at parse time — before this `case`
  -- can answer "absent". The pg_class lookup beside it needs no such care: it reads the catalog by oid.
  -- (`//c/text()` and the coalesce: see row 15.)
  union all
  select 17, 'rollback snapshot (expect absent, or 3 row(s) with RLS enabled+forced and 0 policies)',
         case
           when to_regclass('public.migration_0003_saved_rows') is null then 'absent'
           else coalesce((xpath('//c/text()', query_to_xml(
                  'select count(*) as c from public.migration_0003_saved_rows', false, true, '')))[1]::text,
                  'UNREADABLE')
                || ' row(s), rls ' ||
                coalesce((select c.relrowsecurity::text || '/' || c.relforcerowsecurity::text from pg_class c
                            where c.oid = to_regclass('public.migration_0003_saved_rows')), 'MISSING')
                || ', policies ' ||
                (select count(*)::text from pg_policies
                  where schemaname = 'public' and tablename = 'migration_0003_saved_rows')
         end
) checks
order by ord;
