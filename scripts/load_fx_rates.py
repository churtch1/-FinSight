from __future__ import annotations

import argparse
import csv
from pathlib import Path

from portfolio_mvp.db import get_supabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Load manual FX rates into Supabase.")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    client = get_supabase(use_service_role=True)
    payloads = []
    with open(args.csv_path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            payloads.append(
                {
                    "base_currency": row["base_currency"].strip().upper(),
                    "quote_currency": row.get("quote_currency", "USD").strip().upper(),
                    "rate": row["rate"],
                    "rate_date": row["rate_date"],
                    "source": row.get("source", "manual").strip() or "manual",
                }
            )
    if payloads:
        client.table("fx_rates").upsert(
            payloads,
            on_conflict="base_currency,quote_currency,rate_date,source",
        ).execute()
    print(f"Loaded {len(payloads)} FX rates from {args.csv_path}")


if __name__ == "__main__":
    main()

