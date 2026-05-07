alter table positions_current add column if not exists cost_original numeric(24, 2);
alter table positions_current add column if not exists unrealized_pnl_original numeric(24, 2);
alter table positions_current add column if not exists income_original numeric(24, 2);
alter table positions_current add column if not exists total_pnl_original numeric(24, 2);
alter table positions_current add column if not exists pnl_pct numeric(12, 6);
