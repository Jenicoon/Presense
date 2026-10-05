alter table public.presentation_records
  add column if not exists agent_report jsonb;
