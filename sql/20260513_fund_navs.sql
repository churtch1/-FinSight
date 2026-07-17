create table if not exists fund_navs (
  id uuid primary key default gen_random_uuid(),
  fund_code text not null,
  fund_name text,
  unit_nav numeric(24, 8) not null,
  accumulated_nav numeric(24, 8),
  nav_date date not null,
  announced_at timestamptz,
  source text not null default 'eastmoney',
  status text not null default 'ok',
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(fund_code, nav_date, source)
);

create index if not exists fund_navs_code_date_idx on fund_navs (fund_code, nav_date desc);

alter table positions_current add column if not exists quantity_source text not null default 'reported';
alter table positions_current add column if not exists estimate_note text not null default '';

alter table fund_navs enable row level security;

drop policy if exists "anon read fund_navs" on fund_navs;
create policy "anon read fund_navs" on fund_navs for select to anon using (true);
