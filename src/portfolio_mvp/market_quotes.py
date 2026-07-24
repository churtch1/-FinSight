from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import requests


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: Decimal
    currency: str
    as_of: datetime
    source: str = "yahoo_chart"


class YahooMarketQuoteProvider:
    def __init__(self, timeout: int = 8) -> None:
        self.timeout = timeout
        self.errors: list[str] = []

    def fetch_many(self, symbols: list[str]) -> dict[str, MarketQuote]:
        quotes: dict[str, MarketQuote] = {}
        self.errors = []
        for symbol in sorted({normalize_us_symbol(item) for item in symbols if normalize_us_symbol(item)}):
            try:
                quote = self.fetch_one(symbol)
            except requests.RequestException as exc:
                self.errors.append(f"{symbol}: {exc}")
                continue
            if quote is not None:
                quotes[quote.symbol] = quote
        return quotes

    def fetch_one(self, symbol: str) -> MarketQuote | None:
        normalized = normalize_us_symbol(symbol)
        if not normalized:
            return None
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{normalized}"
        response = requests.get(
            url,
            params={"range": "1d", "interval": "1m"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return parse_yahoo_chart_quote(normalized, payload)


class YahooGoldQuoteProvider:
    """Fetch a gold benchmark and convert it to CNY per gram."""

    TROY_OUNCE_GRAMS = Decimal("31.1034768")

    def __init__(self, symbol: str = "GC=F", timeout: int = 8) -> None:
        self.symbol = symbol
        self.provider = YahooMarketQuoteProvider(timeout=timeout)
        self.errors: list[str] = []

    def fetch_cny_per_gram(self, usd_cny_rate: Decimal) -> MarketQuote | None:
        try:
            quote = self.provider.fetch_one(self.symbol)
        except requests.RequestException as exc:
            self.errors = [f"{self.symbol}: {exc}"]
            return None
        self.errors = list(self.provider.errors)
        if quote is None or quote.price <= 0 or usd_cny_rate <= 0:
            return None
        price = (quote.price * usd_cny_rate / self.TROY_OUNCE_GRAMS).quantize(Decimal("0.000001"))
        return MarketQuote(
            symbol="GOLD-CNY-G",
            price=price,
            currency="CNY",
            as_of=quote.as_of,
            source=f"{quote.source}:{self.symbol}:usd_cny",
        )


def normalize_us_symbol(value: str | None) -> str:
    text = str(value or "").strip().upper()
    if not text or " " in text or text.endswith("CASH"):
        return ""
    return text.replace(".", "-")


def parse_yahoo_chart_quote(symbol: str, payload: dict[str, Any]) -> MarketQuote | None:
    result = (((payload.get("chart") or {}).get("result") or []) or [None])[0]
    if not isinstance(result, dict):
        return None
    meta = result.get("meta") or {}
    price = _decimal(meta.get("regularMarketPrice") or meta.get("previousClose"))
    if price is None or price <= 0:
        return None
    currency = str(meta.get("currency") or "USD").upper()
    timestamp = meta.get("regularMarketTime")
    as_of = datetime.fromtimestamp(int(timestamp), timezone.utc) if timestamp else datetime.now(timezone.utc)
    return MarketQuote(symbol=normalize_us_symbol(symbol), price=price, currency=currency, as_of=as_of)


def _decimal(value: Any) -> Decimal | None:
    try:
        text = str(value or "").replace(",", "").strip()
        return Decimal(text) if text else None
    except (InvalidOperation, ValueError):
        return None
