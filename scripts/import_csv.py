from __future__ import annotations

import argparse
from pathlib import Path

from portfolio_mvp.db import get_supabase
from portfolio_mvp.parsers.csv_normalized import parse_csv
from portfolio_mvp.repository import complete_import, create_import_record, file_sha256, import_normalized_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Import normalized portfolio CSV.")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    client = get_supabase(use_service_role=True)
    rows = parse_csv(args.csv_path)
    import_id = create_import_record(
        client,
        source="normalized_csv",
        source_type="csv",
        file_name=args.csv_path.name,
        file_hash=file_sha256(args.csv_path),
    )
    imported = import_normalized_rows(client, rows, import_id)
    complete_import(client, import_id, imported, "completed")
    print(f"Imported {imported} rows from {args.csv_path}")


if __name__ == "__main__":
    main()

