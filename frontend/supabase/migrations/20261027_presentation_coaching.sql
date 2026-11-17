-- Unknown observations remain SQL NULL, not a zero model score.
alter table public.presentation_records alter column stress_average drop not null;
-- Additive: existing presentation_records and saved reports remain readable.
create table if not exists public.coaching_sessions (
  session_id text not null,
  user_id uuid not null references auth.users on delete cascade,
  snapshot jsonb not null,
  state jsonb not null,
  practices jsonb not null default '[]'::jsonb,
  messages jsonb not null default '[]'::jsonb,
  revision integer not null default 0 check (revision >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, session_id)
);
alter table public.coaching_sessions enable row level security;
grant select, insert, update, delete on public.coaching_sessions to authenticated;
drop policy if exists "Own coaching sessions" on public.coaching_sessions;
create policy "Own coaching sessions" on public.coaching_sessions for all to authenticated
using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create index if not exists coaching_sessions_recent on public.coaching_sessions(user_id, created_at desc);
drop trigger if exists coaching_sessions_updated on public.coaching_sessions;
create trigger coaching_sessions_updated before update on public.coaching_sessions
for each row execute procedure public.handle_updated_at();

-- The authenticated delete also removes its durable raw-analysis snapshot.
create or replace function public.delete_session_coaching() returns trigger
language plpgsql security invoker set search_path = public as $$
begin
  delete from public.coaching_sessions where session_id = old.id::text and user_id = old.user_id;
  return old;
end; $$;
drop trigger if exists presentation_records_delete_coaching on public.presentation_records;
create trigger presentation_records_delete_coaching after delete on public.presentation_records
for each row execute function public.delete_session_coaching();
