create extension if not exists pgcrypto;

do $$ begin
  create type asset_type as enum ('stock', 'fund', 'wealth_product', 'bond', 'cash', 'gold', 'crypto', 'other');
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type transaction_type as enum (
    'buy', 'sell', 'subscribe', 'redeem', 'deposit', 'withdrawal',
    'dividend', 'interest', 'coupon', 'fee', 'tax',
    'cash_balance', 'position_snapshot', 'other'
  );
exception
  when duplicate_object then null;
end $$;

do $$ begin
  create type import_status as enum ('started', 'completed', 'partial', 'needs_review', 'failed');
exception
  when duplicate_object then null;
end $$;

create table if not exists accounts (
  id uuid primary key default gen_random_uuid(),
  provider text not null,
  account_name text not null,
  account_number_masked text,
  account_type text not null default 'other',
  base_currency text not null default 'USD',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider, account_name)
);

create table if not exists instruments (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  name text not null,
  isin text,
  provider_code text,
  currency text,
  asset_type asset_type not null default 'other',
  region text,
  mapping_status text not null default 'needs_review',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists instruments_symbol_currency_idx
  on instruments (symbol, currency)
  where symbol is not null;

create index if not exists instruments_isin_idx on instruments (isin);
create index if not exists instruments_provider_code_idx on instruments (provider_code);
create index if not exists instruments_asset_type_idx on instruments (asset_type);

create table if not exists instrument_aliases (
  id uuid primary key default gen_random_uuid(),
  instrument_id uuid not null references instruments(id) on delete cascade,
  provider text not null default 'unknown',
  alias text not null,
  alias_type text not null default 'auto',
  created_at timestamptz not null default now(),
  unique(provider, alias)
);

create table if not exists statement_imports (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  source_type text not null,
  file_name text,
  file_hash text,
  parser_name text,
  parser_version text,
  status import_status not null default 'started',
  rows_imported integer not null default 0,
  error_summary text,
  imported_at timestamptz,
  created_at timestamptz not null default now(),
  unique(source, file_hash)
);

create table if not exists import_errors (
  id uuid primary key default gen_random_uuid(),
  statement_import_id uuid references statement_imports(id) on delete cascade,
  row_number integer,
  raw_payload jsonb,
  error_message text not null,
  severity text not null default 'error',
  created_at timestamptz not null default now()
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

create table if not exists positions_current (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id) on delete cascade,
  instrument_id uuid not null references instruments(id),
  quantity numeric(24, 8) not null default 0,
  price_original numeric(24, 8),
  market_value_original numeric(24, 2) not null default 0,
  currency text not null,
  market_value_usd numeric(24, 2),
  market_value_cny numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_to_cny numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  valuation_date date not null,
  source text,
  source_import_id uuid references statement_imports(id),
  updated_at timestamptz not null default now(),
  unique(account_id, instrument_id, valuation_date)
);

create index if not exists positions_current_account_idx on positions_current (account_id);
create index if not exists positions_current_instrument_idx on positions_current (instrument_id);
create index if not exists positions_current_date_idx on positions_current (valuation_date desc);

create table if not exists transactions (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id),
  instrument_id uuid references instruments(id),
  source_import_id uuid references statement_imports(id),
  transaction_date date not null,
  transaction_type transaction_type not null,
  quantity numeric(24, 8),
  price_original numeric(24, 8),
  amount_original numeric(24, 2) not null default 0,
  currency text not null,
  amount_usd numeric(24, 2),
  amount_cny numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_to_cny numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  fee_original numeric(24, 2),
  tax_original numeric(24, 2),
  description text,
  created_at timestamptz not null default now()
);

create index if not exists transactions_account_date_idx on transactions (account_id, transaction_date desc);
create index if not exists transactions_import_idx on transactions (source_import_id);

create table if not exists cash_flows (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id),
  source_import_id uuid references statement_imports(id),
  flow_date date not null,
  flow_type text not null,
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  amount_cny numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_to_cny numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create index if not exists cash_flows_account_date_idx on cash_flows (account_id, flow_date desc);

create table if not exists income_records (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references accounts(id),
  instrument_id uuid references instruments(id),
  source_import_id uuid references statement_imports(id),
  income_date date not null,
  income_type text not null,
  amount_original numeric(24, 2) not null,
  currency text not null,
  amount_usd numeric(24, 2),
  amount_cny numeric(24, 2),
  fx_rate_to_usd numeric(24, 10),
  fx_rate_to_cny numeric(24, 10),
  fx_rate_source text,
  fx_rate_date date,
  description text,
  created_at timestamptz not null default now()
);

create index if not exists income_records_account_date_idx on income_records (account_id, income_date desc);

create table if not exists portfolio_snapshots (
  id uuid primary key default gen_random_uuid(),
  snapshot_date date not null unique,
  total_value_usd numeric(24, 2),
  total_value_cny numeric(24, 2),
  total_cost_usd numeric(24, 2),
  total_pnl_usd numeric(24, 2),
  total_pnl_pct numeric(12, 6),
  net_deposit_usd numeric(24, 2),
  created_at timestamptz not null default now()
);

create table if not exists portfolio_snapshot_breakdowns (
  id uuid primary key default gen_random_uuid(),
  snapshot_id uuid not null references portfolio_snapshots(id) on delete cascade,
  dimension text not null,
  key text not null,
  label text not null,
  value_usd numeric(24, 2),
  value_cny numeric(24, 2),
  weight numeric(12, 6),
  created_at timestamptz not null default now(),
  unique(snapshot_id, dimension, key)
);

create index if not exists portfolio_snapshot_breakdowns_dimension_idx
  on portfolio_snapshot_breakdowns (dimension, key);
