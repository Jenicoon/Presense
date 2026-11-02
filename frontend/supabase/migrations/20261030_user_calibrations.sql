begin;

create table if not exists public.user_calibrations (
  user_id uuid primary key references auth.users on delete cascade,
  baseline_score numeric(6, 4) not null check (baseline_score >= 0 and baseline_score <= 1),
  sample_count integer not null check (sample_count >= 3),
  model_version text not null,
  calibrated_at timestamptz not null default timezone('utc', now()),
  last_prompted_at timestamptz
);

alter table public.user_calibrations add column if not exists last_prompted_at timestamptz;

grant select, insert, update, delete on public.user_calibrations to authenticated;
alter table public.user_calibrations enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public'
    and tablename = 'user_calibrations' and policyname = 'Users can manage their own calibration') then
    create policy "Users can manage their own calibration"
    on public.user_calibrations for all to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);
  end if;
end $$;

commit;
