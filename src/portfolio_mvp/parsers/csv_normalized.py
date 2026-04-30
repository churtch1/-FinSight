from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from portfolio_mvp.models import NormalizedRow, TRANSACTION_TYPES, normalize_asset_type


REQUIRED_COLUMNS = {
    "account_name",
    "provider",
    "date",
    "type",
    "amount",
    "currency",
}


def _decimal(value: str | None) -> Decimal:
    if value is None or str(value).strip() == "":
        return Decimal("0")
    return Decimal(str(value).replace(",", "").strip())


def parse_csv(path: str | Path) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        for line_number, raw in enumerate(reader, start=2):
            try:
                row_type = (raw.get("type") or "").strip()
                if row_type not in TRANSACTION_TYPES:
                    raise ValueError(f"Unsupported type: {row_type}")
                rows.append(
                    NormalizedRow(
                        account_name=(raw.get("account_name") or "").strip(),
                        provider=(raw.get("provider") or "").strip(),
                        date=date.fromisoformat((raw.get("date") or "").strip()),
                        type=row_type,
                        instrument_code=(raw.get("instrument_code") or "").strip(),
                        instrument_name=(raw.get("instrument_name") or "").strip(),
                        isin=(raw.get("isin") or "").strip(),
                        asset_type=normalize_asset_type(raw.get("asset_type")),
                        quantity=_decimal(raw.get("quantity")),
                        price=_decimal(raw.get("price")),
                        amount=_decimal(raw.get("amount")),
                        currency=(raw.get("currency") or "").strip().upper(),
                        fee=_decimal(raw.get("fee")),
                        tax=_decimal(raw.get("tax")),
                        description=(raw.get("description") or "").strip(),
                    )
                )
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"CSV line {line_number}: {exc}") from exc
    return rows

