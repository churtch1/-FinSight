create extension if not exists pgcrypto;

do $$ begin
  create type asset_type as enum ('stock', 'fund', 'wealth_product', 'gold', 'cash', 'crypto', 'bond', 'other');
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type transaction_type as enum (
    'buy', 'sell', 'deposit', 'withdrawal', 'dividend', 'interest', 'fee', 'tax', 'cash_balance', 'position_snapshot'
  );
exception
  when duplicate_object then null;
end $$;

create table if not exists accounts (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  account_name text not null,
  account_number text,
  base_currency text not null default 'USD',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider, account_name)
);

create table if not exists instruments (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  name text not null,
  isin text,
  currency text,
  asset_type asset_type not null default 'other',
  mapping_status text not null default 'confirmed',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists instruments_symbol_currency_idx
  on instruments (symbol, currency)
  where symbol is not null;
create index if not exists instruments_isin_idx on instruments (isin);
create index if not exists instruments_asset_type_idx on instruments (asset_type);

create table if not exists instrument_aliases (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references instruments(id) on delete cascade,
  alias text not null,
  alias_type text not null default 'other',
  created_at timestamptz not null default now(),
  unique(alias)
);

create table if not exists fx_rates (
  id uuid primary key default gen_random_uuid(),
  base_currency text not null,
  quote_currency text not null default 'USD',
  rate numeric(24, 10) not null,
  rate_date date not null,
  source text not null default 'manual',
  created_at timestamptz not null default now(),
  unique(base_currency, quote_currency, rate_date, source)
);

create table if not exists statement_imports (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  source_type text not null,
  file_name text,
  file_hash text,
  status text not null default 'started',
  rows_imported integer not null default 0,
  error_summary text,
  created_at timestamptz not null default now(),
  unique(source, file_hash)
);

create table if not exists import_errors (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id) on delete cascade,
  row_number integer,
  raw_payload jsonb,
  error_message text not null,
  created_at timestamptz not null default now()
);

create table if not exists positions_current (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id) on delete cascade,
  instrument_id uuid not null references instruments(id),
  quantity numeric(24, 8) not null default 0,
  price_original numeric(24, 8),
  market_value_original numeric(24, 2) not null default 0,
  currency text not null,
  market_value_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  valuation_date date not null,
  updated_at timestamptz not null default now(),
  unique(account_id, instrument_id, valuation_date)
);

alter table positions_current add column if not exists cost_original numeric(24, 2);
alter table positions_current add column if not exists unrealized_pnl_original numeric(24, 2);
alter table positions_current add column if not exists income_original numeric(24, 2);
alter table positions_current add column if not exists total_pnl_original numeric(24, 2);
alter table positions_current add column if not exists pnl_pct numeric(12, 6);

create table if not exists transactions (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id),
  account_id uuid not null references accounts(id),
  instrument_id uuid references instruments(id),
  transaction_date date not null,
  type transaction_type not null,
  quantity numeric(24, 8),
  price_original numeric(24, 8),
  amount_original numeric(24, 2) not null default 0,
  currency text not null,
  amount_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists cash_flows (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id),
  account_id uuid not null references accounts(id),
  flow_date date not null,
  flow_type text not null,
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists dividends_interest (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id),
  account_id uuid not null references accounts(id),
  instrument_id uuid references instruments(id),
  income_date date not null,
  income_type text not null,
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists fees_taxes (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id),
  account_id uuid not null references accounts(id),
  fee_date date not null,
  fee_type text not null,
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create table if not exists asset_snapshots (
  id uuid primary key default gen_random_uuid(),
  account_id uuid references accounts(id),
  snapshot_date date not null,
  asset_type asset_type not null default 'other',
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  created_at timestamptz not null default now()
);

create or replace view dashboard_positions as
select
  p.*,
  a.provider,
  a.account_name,
  a.base_currency,
  i.symbol,
  i.name as instrument_name,
  i.isin,
  i.asset_type,
  i.mapping_status
from positions_current p
join accounts a on a.id = p.account_id
join instruments i on i.id = p.instrument_id;

alter table accounts enable row level security;
alter table instruments enable row level security;
alter table instrument_aliases enable row level security;
alter table fx_rates enable row level security;
alter table statement_imports enable row level security;
alter table import_errors enable row level security;
alter table positions_current enable row level security;
alter table transactions enable row level security;
alter table cash_flows enable row level security;
alter table dividends_interest enable row level security;
alter table fees_taxes enable row level security;
alter table asset_snapshots enable row level security;

do $$ declare
  t text;
begin
  foreach t in array array[
    'accounts', 'instruments', 'instrument_aliases', 'fx_rates', 'statement_imports', 'import_errors',
    'positions_current', 'transactions', 'cash_flows', 'dividends_interest', 'fees_taxes', 'asset_snapshots'
  ]
  loop
    execute format('drop policy if exists "anon read %1$s" on %1$I', t);
    execute format('create policy "anon read %1$s" on %1$I for select to anon using (true)', t);
  end loop;
end $$;
