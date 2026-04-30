from __future__ import annotations

import argparse

from portfolio_mvp.db import get_supabase
from portfolio_mvp.integrations.ibkr import sync_ibkr_rows
from portfolio_mvp.repository import complete_import, create_import_record, import_normalized_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IBKR data from local IB Gateway/TWS.")
    parser.add_argument("--account", default="all")
    args = parser.parse_args()

    rows = sync_ibkr_rows(account=args.account)
    client = get_supabase(use_service_role=True)
    import_id = create_import_record(
        client,
        source="ibkr",
        source_type="api",
        file_name=None,
        file_hash=f"ibkr-{args.account}",
    )
    imported = import_normalized_rows(client, rows, import_id)
    complete_import(client, import_id, imported, "completed")
    print(f"Synced {imported} IBKR rows.")


if __name__ == "__main__":
    main()

