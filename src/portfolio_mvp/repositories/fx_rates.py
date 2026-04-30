from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from portfolio_mvp.fx import FxRate

if TYPE_CHECKING:
    from supabase import Client


@dataclass(frozen=True)
class ConvertedAmount:
    value: Decimal | None
    rate: Decimal | None
    source: str | None
    rate_date: date | None


def load_fx_rows(client: "Client") -> list[dict[str, Any]]:
    return client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []


def latest_rate_for_pair(base_currency: str, quote_currency: str, rows: list[dict[str, Any]]) -> FxRate | None:
    base_currency = base_currency.upper()
    quote_currency = quote_currency.upper()
    if base_currency == quote_currency:
        return FxRate(base_currency, quote_currency, Decimal("1"), date.today(), "identity")
    for row in rows:
        if (
            str(row.get("base_currency", "")).upper() == base_currency
            and str(row.get("quote_currency", "")).upper() == quote_currency
        ):
            return FxRate(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=Decimal(str(row["rate"])),
                rate_date=date.fromisoformat(str(row["rate_date"])),
                source=str(row.get("source") or "cached"),
            )
    return None


def convert_amount(amount: Decimal, currency: str, target_currency: str, rows: list[dict[str, Any]]) -> ConvertedAmount:
    currency = currency.upper()
    target_currency = target_currency.upper()
    direct = latest_rate_for_pair(currency, target_currency, rows)
    if direct:
        return ConvertedAmount(
            value=(amount * direct.rate).quantize(Decimal("0.01")),
            rate=direct.rate,
            source=direct.source,
            rate_date=direct.rate_date,
        )

    # Fall back through USD when both legs are available.
    to_usd = latest_rate_for_pair(currency, "USD", rows)
    target_to_usd = latest_rate_for_pair(target_currency, "USD", rows)
    if to_usd and target_to_usd and target_to_usd.rate != 0:
        cross_rate = to_usd.rate / target_to_usd.rate
        return ConvertedAmount(
            value=(amount * cross_rate).quantize(Decimal("0.01")),
            rate=cross_rate,
            source=f"{to_usd.source}/{target_to_usd.source}",
            rate_date=min(to_usd.rate_date, target_to_usd.rate_date),
        )

    return ConvertedAmount(value=None, rate=None, source=None, rate_date=None)

