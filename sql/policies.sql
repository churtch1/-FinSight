alter table accounts enable row level security;
alter table instruments enable row level security;
alter table instrument_aliases enable row level security;
alter table statement_imports enable row level security;
alter table import_errors enable row level security;
alter table fx_rates enable row level security;
alter table positions_current enable row level security;
alter table transactions enable row level security;
alter table cash_flows enable row level security;
alter table income_records enable row level security;
alter table portfolio_snapshots enable row level security;
alter table portfolio_snapshot_breakdowns enable row level security;

do $$ declare
  t text;
begin
  foreach t in array array[
    'accounts',
    'instruments',
    'instrument_aliases',
    'statement_imports',
    'import_errors',
    'fx_rates',
    'positions_current',
    'transactions',
    'cash_flows',
    'income_records',
    'portfolio_snapshots',
    'portfolio_snapshot_breakdowns'
  ]
  loop
    execute format('drop policy if exists "anon read %1$s" on %1$I', t);
    execute format('create policy "anon read %1$s" on %1$I for select to anon using (true)', t);
  end loop;
end $$;
