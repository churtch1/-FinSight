from __future__ import annotations

import argparse
from datetime import datetime, timezone

from portfolio_mvp.db import MissingSupabaseConfig, get_supabase
from portfolio_mvp.integrations.ibkr import sync_ibkr_data
from portfolio_mvp.repository import complete_import, create_import_record, import_normalized_rows, log_import_error, upsert_account


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync IBKR data from local IB Gateway/TWS.")
    parser.add_argument("--account", default="all")
    args = parser.parse_args()

    try:
        client = get_supabase(use_service_role=True)
    except MissingSupabaseConfig as exc:
        raise SystemExit(str(exc)) from exc

    sync_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    import_id = create_import_record(
        client,
        source="ibkr",
        source_type="api",
        file_name=None,
        file_hash=f"ibkr-{args.account}-{sync_started_at}",
    )

    try:
        data = sync_ibkr_data(account=args.account)
        for account_name in data.accounts:
            summary = data.account_summaries.get(account_name, {})
            upsert_account(client, "IBKR", account_name, summary.get("BaseCurrency", "USD") or "USD")

        imported = import_normalized_rows(client, data.rows, import_id)
        if imported == len(data.rows):
            complete_import(client, import_id, imported, "completed")
        else:
            failed = len(data.rows) - imported
            complete_import(client, import_id, imported, "needs_review", f"{failed} rows failed during import.")
        print(f"Synced {imported}/{len(data.rows)} IBKR rows across {len(data.accounts)} account(s).")
    except Exception as exc:
        log_import_error(client, import_id, None, {"account": args.account}, str(exc))
        complete_import(client, import_id, 0, "failed", str(exc))
        raise SystemExit(f"IBKR sync failed: {exc}") from exc


if __name__ == "__main__":
    main()

