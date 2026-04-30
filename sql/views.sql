create or replace view dashboard_positions as
select
  p.*,
  a.provider,
  a.account_name,
  a.account_type,
  a.base_currency,
  i.symbol,
  i.name as instrument_name,
  i.isin,
  i.provider_code,
  i.asset_type,
  i.region,
  i.mapping_status
from positions_current p
join accounts a on a.id = p.account_id
join instruments i on i.id = p.instrument_id;

create or replace view dashboard_allocation_by_account as
select
  a.provider,
  a.account_name,
  sum(coalesce(p.market_value_usd, 0)) as value_usd,
  sum(coalesce(p.market_value_cny, 0)) as value_cny
from positions_current p
join accounts a on a.id = p.account_id
group by a.provider, a.account_name;

create or replace view dashboard_allocation_by_asset_type as
select
  i.asset_type,
  sum(coalesce(p.market_value_usd, 0)) as value_usd,
  sum(coalesce(p.market_value_cny, 0)) as value_cny
from positions_current p
join instruments i on i.id = p.instrument_id
group by i.asset_type;

create or replace view dashboard_allocation_by_currency as
select
  p.currency,
  sum(coalesce(p.market_value_usd, 0)) as value_usd,
  sum(coalesce(p.market_value_cny, 0)) as value_cny,
  sum(coalesce(p.market_value_original, 0)) as value_original
from positions_current p
group by p.currency;

create or replace view dashboard_net_worth_history as
select
  snapshot_date,
  total_value_usd,
  total_value_cny,
  total_pnl_usd,
  total_pnl_pct,
  net_deposit_usd
from portfolio_snapshots
order by snapshot_date;

create or replace view dashboard_import_status as
select
  id,
  source,
  source_type,
  file_name,
  parser_name,
  parser_version,
  status,
  rows_imported,
  error_summary,
  coalesce(imported_at, created_at) as imported_at
from statement_imports
order by coalesce(imported_at, created_at) desc;
