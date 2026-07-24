from __future__ import annotations

from decimal import Decimal

import requests

from portfolio_mvp.market_quotes import normalize_us_symbol, parse_yahoo_chart_quote
from portfolio_mvp.market_quotes import YahooMarketQuoteProvider


def test_parse_yahoo_chart_quote_reads_price_currency_and_timestamp() -> None:
    quote = parse_yahoo_chart_quote(
        "AAPL",
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 191.25,
                            "regularMarketTime": 1779300000,
                            "currency": "USD",
                        }
                    }
                ]
            }
        },
    )

    assert quote is not None
    assert quote.symbol == "AAPL"
    assert quote.price == Decimal("191.25")
    assert quote.currency == "USD"
    assert quote.as_of.year == 2026


def test_normalize_us_symbol_skips_cash_and_blank_symbols() -> None:
    assert normalize_us_symbol(" brk.b ") == "BRK-B"
    assert normalize_us_symbol("USD CASH") == ""
    assert normalize_us_symbol("") == ""


def test_fetch_many_keeps_going_when_one_symbol_is_rate_limited() -> None:
    class FakeProvider(YahooMarketQuoteProvider):
        def fetch_one(self, symbol: str):  # type: ignore[override]
            if symbol == "AAPL":
                raise requests.HTTPError("429 Client Error")
            return parse_yahoo_chart_quote(
                symbol,
                {
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "regularMarketPrice": 191.25,
                                    "regularMarketTime": 1779300000,
                                    "currency": "USD",
                                }
                            }
                        ]
                    }
                },
            )

    provider = FakeProvider()
    quotes = provider.fetch_many(["AAPL", "MSFT"])

    assert sorted(quotes) == ["MSFT"]
    assert provider.errors == ["AAPL: 429 Client Error"]
