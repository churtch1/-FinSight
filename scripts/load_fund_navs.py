from __future__ import annotations

import argparse
from pathlib import Path

from portfolio_mvp.db import get_supabase
from portfolio_mvp.fund_nav import AutomaticFundNavProvider, normalize_fund_code, parse_fund_nav_csv
from portfolio_mvp.repository import upsert_fund_navs


def main() -> None:
    parser = argparse.ArgumentParser(description="Load or fetch fund NAVs into Supabase.")
    parser.add_argument("--csv", type=Path, help="CSV with fund_code,fund_name,unit_nav,nav_date columns.")
    parser.add_argument("--fund-code", action="append", default=[], help="Fund code to fetch from the online provider. Repeatable.")
    args = parser.parse_args()

    navs = []
    if args.csv:
        navs.extend(parse_fund_nav_csv(args.csv))

    fund_codes = sorted({normalize_fund_code(item) for item in args.fund_code if normalize_fund_code(item)})
    if fund_codes:
        provider = AutomaticFundNavProvider()
        navs.extend(provider.fetch_many(fund_codes).values())

    client = get_supabase(use_service_role=True)
    loaded = upsert_fund_navs(client, navs)
    print(f"Loaded {loaded} fund NAV rows.")


if __name__ == "__main__":
    main()
