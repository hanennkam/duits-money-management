-- STAGING ONLY. Repairs the state left by an earlier 0002 up run whose step 3 matched nothing (a regex that
-- ended in \m instead of \M). The fixed migrations/0002_multi_user.up.sql does this itself on a clean run.
-- Do not run this on the live project. Run it once in the STAGING SQL editor, in one session.
-- It refuses to run unless the global constraint is still there, so a second run does nothing and fails.

begin;

-- 0. Only repair the state the bad run left: the global dedupe constraint must still exist.
do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conrelid = 'public.transactions'::regclass
       and conname = 'transactions_dedupe_hash_key'
  ) then
    raise exception 'transactions_dedupe_hash_key is not present: this repair does not apply to this state';
  end if;
end $$;

-- 1. The partial per-owner indexes the bad run created are replaced by UNIQUE (user_id, ...) constraints.
drop index if exists public.transactions_user_dedupe_key;
drop index if exists public.transactions_user_image_key;

-- 2. The global constraint goes, by its real name.
alter table public.transactions drop constraint transactions_dedupe_hash_key;

-- 3. Per-owner uniqueness, as the fixed up file creates it.
alter table public.transactions add constraint transactions_user_dedupe_key unique (user_id, dedupe_hash);
alter table public.transactions add constraint transactions_user_image_key unique (user_id, image_hash);

-- 4. Record the original global constraint, so the rollback restores it (the snapshot was empty).
delete from public.migration_0002_saved_constraints;
insert into public.migration_0002_saved_constraints (kind, name, definition) values (
  'constraint',
  'transactions_dedupe_hash_key',
  'alter table public.transactions add constraint transactions_dedupe_hash_key UNIQUE (dedupe_hash)'
);

commit;
