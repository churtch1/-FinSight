from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_mvp.config import Settings, get_settings


@dataclass(frozen=True)
class FxRate:
    base_currency: str
    quote_currency: str
    rate: Decimal
    rate_date: date
    source: str


def convert_to_usd(amount: Decimal, currency: str, fx_rate: FxRate | None) -> Decimal | None:
    if currency.upper() == "USD":
        return amount
    if fx_rate is None:
        return None
    return (amount * fx_rate.rate).quantize(Decimal("0.01"))


def fetch_online_usd_rates(settings: Settings | None = None) -> dict[str, FxRate]:
    """Fetch latest USD-based exchange rates.

    Default API returns USD -> currency. We invert to currency -> USD for storage.
    """
    settings = settings or get_settings()
    import requests

    response = requests.get(settings.fx_api_url, timeout=8)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    rates = payload.get("rates", {})
    rate_date = date.today()
    if payload.get("time_last_update_unix"):
        try:
            from datetime import datetime, timezone

            rate_date = datetime.fromtimestamp(int(payload["time_last_update_unix"]), tz=timezone.utc).date()
        except Exception:
            rate_date = date.today()
    output: dict[str, FxRate] = {
        "USD": FxRate("USD", "USD", Decimal("1"), rate_date, "online")
    }
    for currency, usd_to_ccy in rates.items():
        value = Decimal(str(usd_to_ccy))
        if value == 0:
            continue
        output[currency.upper()] = FxRate(currency.upper(), "USD", (Decimal("1") / value), rate_date, "online")
    return output


def latest_rate_from_rows(currency: str, rows: list[dict[str, Any]]) -> FxRate | None:
    currency = currency.upper()
    if currency == "USD":
        return FxRate("USD", "USD", Decimal("1"), date.today(), "identity")
    for row in rows:
        if row.get("base_currency", "").upper() == currency and row.get("quote_currency", "USD").upper() == "USD":
            return FxRate(
                base_currency=currency,
                quote_currency="USD",
                rate=Decimal(str(row["rate"])),
                rate_date=date.fromisoformat(str(row["rate_date"])),
                source=str(row.get("source") or "cached"),
            )
    return None
