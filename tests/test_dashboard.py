from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from portfolio_mvp.dashboard import (
    account_summary,
    asset_summary,
    currency_summary,
    dashboard_summary,
    filter_positions,
    paginate,
    top_holdings,
)


def _positions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "provider": "IBKR",
                "account_name": "IBKR Demo",
                "symbol": "NVDA",
                "instrument_name": "NVIDIA CORP",
                "asset_type": "stock",
                "quantity": 10,
                "price_original": 900,
                "market_value_original": 9000,
                "currency": "USD",
                "market_value_usd": 9000,
                "valuation_date": "2026-04-30",
            },
            {
                "provider": "HSBC China",
                "account_name": "HSBC China",
                "symbol": "CNY CASH",
                "instrument_name": "CNY Cash",
                "asset_type": "cash",
                "quantity": 50000,
                "price_original": 1,
                "market_value_original": 50000,
                "currency": "CNY",
                "market_value_usd": 6900,
                "valuation_date": "2026-04-30",
            },
        ]
    )


def test_dashboard_summary_includes_concentration_metrics() -> None:
    positions = _positions()
    imports = pd.DataFrame([{"status": "completed"}])
    errors = pd.DataFrame([{"error_message": "needs review"}])

    summary = dashboard_summary(positions, imports, errors)

    assert summary.total_usd == 15900
    assert summary.account_count == 2
    assert summary.provider_count == 2
    assert summary.position_count == 2
    assert round(summary.cash_ratio, 2) == round(6900 / 15900 * 100, 2)
    assert round(summary.top_holding_ratio, 2) == round(9000 / 15900 * 100, 2)
    assert summary.latest_import_status == "completed"


def test_allocation_summaries() -> None:
    positions = _positions()

    assets = asset_summary(positions)
    accounts = account_summary(positions)
    currencies = currency_summary(positions)

    assert set(assets["asset_label"]) == {"股票", "现金"}
    assert accounts["market_value_usd"].sum() == 15900
    assert set(currencies["currency"]) == {"USD", "CNY"}


def test_filter_top_holdings_and_paginate() -> None:
    positions = _positions()

    filtered = filter_positions(positions, asset_type="cash", provider="HSBC China", currency="CNY", query="cash", min_value=1000)
    top = top_holdings(positions, limit=1)
    page, total_pages = paginate(filtered, page=1, page_size=1)

    assert len(filtered) == 1
    assert page.iloc[0]["symbol"] == "CNY CASH"
    assert top.iloc[0]["symbol"] == "NVDA"
    assert total_pages == 1
