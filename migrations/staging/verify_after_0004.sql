-- migrations/staging/verify_after_0004.sql
-- READ-ONLY verification for 0004_commitment_link (the Pay-flow link column and the wider view). Selects
-- only: it writes nothing and names no project, so the same file serves the STAGING rehearsal and any
-- later live run. Run it BEFORE the up file as well as after it — the grid names the state it finds, so
-- a "before" run is the picture the "after" run is compared against.
--
-- ONE statement, ONE result grid. Read each row's `value` and compare it with the expectation written in
-- that row's own `check_name`. Anything that does not match is a stop, not a judgement call.
--
-- THE RUN ORDER (staging first; the same five steps on live, with its own pg_dump).
--   1. Backup staging with pg_dump and note the file's path. Nothing else starts without it.
--   2. Run THIS grid first and keep rows 4 and 8: they are the "before" picture (the view's columns and
--      the transactions row count).
--   3. Run migrations/0004_commitment_link.up.sql in the SQL editor, in ONE session. Expected: no error.
--      Any error rolls the whole file back, so the project is unchanged — read the message and stop.
--   4. Run THIS grid again. Expect: row 1 `uuid / YES`, row 3 no foreign key on commitment_id, row 4
--      seven columns ending in commitment_expense, row 5 `7 of 7 / numeric`, row 8 the SAME row count
--      as before, row 9 zero.
--   5. Re-run migrations/staging/verify_after_0003.sql: 0003 must still read clean, and its row 16
--      (transactions rows) must be the same number as this file's row 8.
--   6. Run the isolation suite: ./.venv/bin/python scripts/run_staging_tests.py
--   ROLLBACK, if step 3, 4, 5 or 6 fails: run migrations/0004_commitment_link.down.sql in ONE session
--   (no set_config is needed — 0004 destroys no typed row, only the links), then run THIS grid again and
--   expect the "before" picture back: row 1 MISSING, row 4 six columns, row 5 MISSING. Investigate
--   only after the rollback has been confirmed.
--
-- The file is safe to run in ANY state — 0004 applied, not applied, or rolled back. Every object that may
-- legitimately be absent is read through a string (to_regclass, query_to_xml) or through the catalog
-- (information_schema, pg_catalog), never named in code position: Postgres resolves a relation name while
-- it PARSES the statement, before any guard is evaluated (docs/migration-runbook.md §10 step 2).
--
-- Row 0 is the prerequisite: 0004 is built on 0003, so the 0003 view and the 0003 commitments table must
-- both be there. Everything below reads MISSING when they are not.

select ord, check_name, value
from (
  select 0 as ord,
         '0003 is applied: transaction_totals / monthly_commitments (expect present / present)' as check_name,
         case when to_regclass('public.transaction_totals') is null then 'MISSING (0003 is not applied)'
              else 'present' end
         || ' / ' ||
         case when to_regclass('public.monthly_commitments') is null then 'MISSING (0003 is not applied)'
              else 'present' end as value
  union all
  -- The link column itself. Nullable by design: every row that is not from the Pay flow stays null.
  select 1,
         'transactions.commitment_id (expect uuid / YES; MISSING = 0004 up has not run, or was rolled back)',
         coalesce((select c.data_type || ' / ' || c.is_nullable
                     from information_schema.columns c
                    where c.table_schema = 'public'
                      and c.table_name = 'transactions'
                      and c.column_name = 'commitment_id'),
                   'MISSING (0004 is not applied: public.transactions.commitment_id does not exist)')
  union all
  -- The column must be able to hold the id it is given: monthly_commitments.id is the value a Pay save
  -- sends, so the two types have to be the same.
  select 2,
         'commitment_id type vs monthly_commitments.id (expect uuid = uuid)',
         coalesce((select (select data_type from information_schema.columns
                            where table_schema = 'public' and table_name = 'transactions' and column_name = 'commitment_id')
                        || ' = ' ||
                        (select data_type from information_schema.columns
                            where table_schema = 'public' and table_name = 'monthly_commitments' and column_name = 'id')),
                   'MISSING (0004 or 0003 is not applied)')
  union all
  -- 0004 adds NO foreign key, ON PURPOSE: a cascade would take an expense with a deleted commitment, and
  -- a composite FK over (commitment_id, user_id) would force `on delete set null` onto the NOT NULL
  -- user_id. The API polices ownership instead (404 for a commitment that is not the caller's). The only
  -- foreign key that may be here is 0002's user_id.
  select 3,
         'foreign keys on transactions (expect only FOREIGN KEY (user_id) REFERENCES auth.users(id); none on commitment_id)',
         case when to_regclass('public.transactions') is null then 'MISSING (no table, so no foreign keys to report)'
              else coalesce((select string_agg(pg_get_constraintdef(c.oid), ' | ' order by c.conname)
                               from pg_constraint c
                              where c.conrelid = to_regclass('public.transactions') and c.contype = 'f'), 'none')
              || ' ; on commitment_id: ' ||
              coalesce((select count(*)::text
                          from pg_constraint c
                         where c.conrelid = to_regclass('public.transactions')
                           and c.contype = 'f'
                           and pg_get_constraintdef(c.oid) like '%commitment_id%'), '0')
         end
  union all
  -- The view's outputs, in the order the API and the SQL files expect: 0003's six, then the new one.
  select 4,
         'transaction_totals columns, in order (expect user_id, mode, month, total_income, total_expense, row_count, commitment_expense)',
         case when to_regclass('public.transaction_totals') is null then 'MISSING (0003 is not applied)'
              else coalesce((select string_agg(column_name || ' ' || data_type, ', ' order by ordinal_position)
                               from information_schema.columns
                              where table_schema = 'public' and table_name = 'transaction_totals'),
                            'MISSING')
         end
  union all
  -- The column 42P16 was about: CREATE OR REPLACE VIEW may only APPEND a column, so this one has to be
  -- the LAST one. Position of 7 of 7 is the proof; a position of 6 of 7 is the bug that failed on
  -- staging on 2026-10-19.
  select 5,
         'commitment_expense position and type (expect 7 of 7 / numeric — LAST, because a replace may only append)',
         case when to_regclass('public.transaction_totals') is null then 'MISSING (0003 is not applied)'
              when not exists (select 1 from information_schema.columns
                                where table_schema = 'public' and table_name = 'transaction_totals'
                                  and column_name = 'commitment_expense')
                then 'MISSING (0004 is not applied: the view has no commitment_expense)'
              else (select ordinal_position::text || ' of ' ||
                             (select max(ordinal_position)::text from information_schema.columns
                               where table_schema = 'public' and table_name = 'transaction_totals')
                             || ' / ' || data_type
                      from information_schema.columns
                     where table_schema = 'public' and table_name = 'transaction_totals'
                       and column_name = 'commitment_expense')
         end
  union all
  select 6,
         'transaction_totals is a view and security_invoker (expect v / true)',
         coalesce((select c.relkind::text || ' / ' || coalesce(('security_invoker=true' = any(c.reloptions))::text, 'false')
                     from pg_class c join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public' and c.relname = 'transaction_totals'), 'MISSING')
  union all
  -- The view has no policy of its own, so its grants are the whole gate for anyone who is not the
  -- service key. A missing view reads MISSING: has_table_privilege on a relation that is not there
  -- raises, which would break the run.
  select 7,
         'SELECT privilege on transaction_totals for anon / authenticated / service_role (expect false / false / true)',
         case when to_regclass('public.transaction_totals') is null then 'MISSING (no view, so no grants to report)'
              else has_table_privilege('anon', 'public.transaction_totals', 'select')::text || ' / ' ||
                   has_table_privilege('authenticated', 'public.transaction_totals', 'select')::text || ' / ' ||
                   has_table_privilege('service_role', 'public.transaction_totals', 'select')::text
         end
  union all
  -- 0004 must not move a transaction: it adds a column and widens a view, nothing else.
  select 8,
         'transactions rows (expect the SAME number as before the run — compare with the "before" run of this grid and with verify_after_0003.sql row 16)',
         case when to_regclass('public.transactions') is null then 'MISSING'
              else coalesce((xpath('//c/text()', query_to_xml(
                       'select count(*) as c from public.transactions', false, true, '')))[1]::text, 'UNREADABLE')
         end
  union all
  -- No backfill: 0004 cannot tell a past Pay row from any other expense, so the column starts empty and
  -- only the Pay flow ever writes it.
  select 9,
         'transactions rows with commitment_id set (expect 0 — 0004 has no backfill)',
         case when not exists (select 1 from information_schema.columns
                                where table_schema = 'public' and table_name = 'transactions'
                                  and column_name = 'commitment_id')
              then 'MISSING (0004 is not applied)'
              else coalesce((xpath('//c/text()', query_to_xml(
                       'select count(*) as c from public.transactions where commitment_id is not null',
                       false, true, '')))[1]::text, 'UNREADABLE')
         end
  union all
  -- The API's own column list, read exactly as app/db.py asks for it. This is the row that says the
  -- deployed code can read the view — it is the call /finance/summary makes.
  select 10,
         'the API''s own column list is readable (app/db.py: mode, month, total_income, total_expense, commitment_expense, row_count) — expect a row count, not an error',
         case when to_regclass('public.transaction_totals') is null then 'MISSING (0003 is not applied)'
              when not exists (select 1 from information_schema.columns
                                where table_schema = 'public' and table_name = 'transaction_totals'
                                  and column_name = 'commitment_expense')
                then 'MISSING (0004 is not applied: the view has no commitment_expense)'
              else coalesce((xpath('//c/text()', query_to_xml(
                       'select count(*) as c from (select mode, month, total_income, total_expense, commitment_expense, row_count from public.transaction_totals) t',
                       false, true, '')))[1]::text, 'UNREADABLE')
         end
  union all
  -- The view's rows that carry a Pay expense. Zero until a Pay save happens; the first one is the
  -- proof that the link is being written and read.
  select 11,
         'view rows with commitment_expense > 0 (expect 0 until the first Pay save)',
         case when to_regclass('public.transaction_totals') is null then 'MISSING (0003 is not applied)'
              when not exists (select 1 from information_schema.columns
                                where table_schema = 'public' and table_name = 'transaction_totals'
                                  and column_name = 'commitment_expense')
                then 'MISSING (0004 is not applied: the view has no commitment_expense)'
              else coalesce((xpath('//c/text()', query_to_xml(
                       'select count(*) as c from public.transaction_totals where commitment_expense > 0',
                       false, true, '')))[1]::text, 'UNREADABLE')
         end
  union all
  -- The definition, for the record: the last line of its select list must be commitment_expense.
  select 12,
         'transaction_totals definition (for the record: the last output must be commitment_expense)',
         case when to_regclass('public.transaction_totals') is null then 'MISSING'
              else pg_get_viewdef(to_regclass('public.transaction_totals'), true)
         end
  union all
  -- 0004 adds exactly one column. Anything else on the table that mentions a commitment would mean a
  -- different migration has been applied on top.
  select 13,
         'transactions columns mentioning commitment (expect only: commitment_id)',
         coalesce((select string_agg(column_name, ', ' order by ordinal_position)
                     from information_schema.columns
                    where table_schema = 'public' and table_name = 'transactions'
                      and column_name like '%commitment%'), 'none')
) checks
order by ord;
