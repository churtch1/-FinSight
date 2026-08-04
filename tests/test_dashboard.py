from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pandas as pd


def load_dashboard_module():
    module_path = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    spec = importlib.util.spec_from_file_location("streamlit_app", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_localized_instrument_name_translates_ibkr_bond_and_stock() -> None:
    dashboard = load_dashboard_module()

    assert dashboard.localized_instrument_name("AAPL", "Apple Inc.") == "苹果"
    assert (
        dashboard.localized_instrument_name("IBCID37926925", "US-T (IBCID37926925)")
        == "美国国债 (IBCID37926925)"
    )


def test_aggregate_spotlight_positions_sums_value_cost_and_pnl() -> None:
    dashboard = load_dashboard_module()
    frame = pd.DataFrame(
        [
            {
                "asset_type": "stock",
                "symbol": "AAPL",
                "display_name": "苹果",
                "display_value": 1000.0,
                "display_cost": 800.0,
                "display_pnl": 200.0,
            },
            {
                "asset_type": "stock",
                "symbol": "AAPL",
                "display_name": "苹果",
                "display_value": 500.0,
                "display_cost": 400.0,
                "display_pnl": 100.0,
            },
            {
                "asset_type": "bond",
                "symbol": "IBCID1",
                "display_name": "美国国债 (IBCID1)",
                "display_value": 2000.0,
                "display_cost": 1900.0,
                "display_pnl": 100.0,
            },
        ]
    )

    grouped = dashboard.aggregate_spotlight_positions(frame, "stock")

    assert len(grouped) == 1
    row = grouped.iloc[0]
    assert row["symbol"] == "AAPL"
    assert row["display_value"] == 1500.0
    assert row["display_cost"] == 1200.0
    assert row["display_pnl"] == 300.0
    assert round(float(row["pnl_pct"]), 4) == 0.25


def test_apply_fund_nav_estimates_updates_fund_value_and_pnl() -> None:
    dashboard = load_dashboard_module()
    positions = pd.DataFrame(
        [
            {
                "asset_type": "fund",
                "symbol": "270023",
                "quantity": 1000,
                "price_original": 2.0,
                "market_value_original": 2000.0,
                "market_value_usd": 276.0,
                "currency": "CNY",
                "cost_original": 1800.0,
                "total_pnl_original": 200.0,
                "unrealized_pnl_original": 200.0,
                "estimate_note": "",
            }
        ]
    )
    navs = pd.DataFrame(
        [
            {
                "fund_code": "270023",
                "fund_name": "GF Global Select",
                "unit_nav": "2.3456",
                "nav_date": "2026-05-11",
                "source": "manual",
                "status": "ok",
            }
        ]
    )
    rate_map = {"CNY": dashboard.FxRate("CNY", "USD", Decimal("0.14"), date(2026, 5, 11), "manual")}

    updated = dashboard.apply_fund_nav_estimates(positions, navs, rate_map)

    assert updated.loc[0, "price_original"] == 2.3456
    assert updated.loc[0, "market_value_original"] == 2345.6
    assert round(float(updated.loc[0, "market_value_usd"]), 2) == 328.38
    assert round(float(updated.loc[0, "total_pnl_original"]), 2) == 545.60
    assert updated.loc[0, "fund_nav_date"] == "2026-05-11"


def test_daily_return_series_supports_total_wealth_and_investment_modes() -> None:
    dashboard = load_dashboard_module()
    history = pd.DataFrame(
        [
            {
                "provider": "IBKR",
                "account_name": "A",
                "valuation_date": date(2026, 7, 1),
                "asset_type": "stock",
                "currency": "USD",
                "market_value_original": 1100,
                "market_value_usd": 1100,
                "cost_original": 1000,
                "total_pnl_original": 100,
                "unrealized_pnl_original": 100,
            },
            {
                "provider": "IBKR",
                "account_name": "A",
                "valuation_date": date(2026, 7, 2),
                "asset_type": "stock",
                "currency": "USD",
                "market_value_original": 1120,
                "market_value_usd": 1120,
                "cost_original": 1000,
                "total_pnl_original": 120,
                "unrealized_pnl_original": 120,
            },
            {
                "provider": "CMB",
                "account_name": "B",
                "valuation_date": date(2026, 7, 1),
                "asset_type": "wealth_product",
                "currency": "USD",
                "market_value_original": 1050,
                "market_value_usd": 1050,
                "cost_original": 1000,
                "total_pnl_original": 50,
                "unrealized_pnl_original": 50,
            },
            {
                "provider": "CMB",
                "account_name": "B",
                "valuation_date": date(2026, 7, 2),
                "asset_type": "wealth_product",
                "currency": "USD",
                "market_value_original": 1055,
                "market_value_usd": 1055,
                "cost_original": 1000,
                "total_pnl_original": 55,
                "unrealized_pnl_original": 55,
            },
        ]
    )
    rates = {"USD": dashboard.FxRate("USD", "USD", Decimal("1"), date(2026, 7, 2), "identity")}

    total = dashboard.build_daily_return_series(history, "总收益", date(2026, 7, 1), date(2026, 7, 2), "USD", rates)
    wealth = dashboard.build_daily_return_series(history, "理财收益", date(2026, 7, 1), date(2026, 7, 2), "USD", rates)
    investment = dashboard.build_daily_return_series(history, "投资收益", date(2026, 7, 1), date(2026, 7, 2), "USD", rates)

    assert total.loc[1, "return"] == 25
    assert wealth.loc[1, "return"] == 5
    assert investment.loc[1, "return"] == 20


def test_complete_account_snapshot_carries_unchanged_holdings_forward() -> None:
    dashboard = load_dashboard_module()

    class Query:
        def __init__(self, writes):
            self.writes = writes
            self.payload = None

        def upsert(self, payload, on_conflict=None):
            self.payload = payload
            return self

        def execute(self):
            self.writes.append(self.payload)
            return SimpleNamespace(data=[])

    class Client:
        def __init__(self):
            self.writes = []

        def table(self, name):
            assert name == "positions_current"
            return Query(self.writes)

    rows = [
        {
            "account_id": "account-1",
            "instrument_id": "fund-1",
            "quantity": "100",
            "price_original": "1.00",
            "market_value_original": "100.00",
            "currency": "CNY",
            "valuation_date": "2026-08-03",
            "instruments": {"symbol": "012920", "asset_type": "fund"},
        },
        {
            "account_id": "account-1",
            "instrument_id": "cash-1",
            "quantity": "1",
            "price_original": "500.00",
            "market_value_original": "500.00",
            "currency": "CNY",
            "valuation_date": "2026-08-03",
            "instruments": {"symbol": "CNY CASH", "asset_type": "cash"},
        },
    ]
    changes = {
        ("account-1", "fund-1"): (
            date(2026, 8, 4),
            {"price_original": "1.05", "market_value_original": "105.00"},
        )
    }
    client = Client()

    written = dashboard.write_complete_account_snapshots(client, rows, changes)

    assert written == 2
    assert {row["instrument_id"] for row in client.writes} == {"fund-1", "cash-1"}
    assert all(row["valuation_date"] == "2026-08-04" for row in client.writes)
    fund = next(row for row in client.writes if row["instrument_id"] == "fund-1")
    cash = next(row for row in client.writes if row["instrument_id"] == "cash-1")
    assert fund["market_value_original"] == "105.00"
    assert cash["market_value_original"] == "500.00"


def test_has_valid_auth_query_accepts_signed_unexpired_token(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    settings = SimpleNamespace(streamlit_password="secret")
    expires_at = 4102444800
    signature = dashboard.auth_query_signature("secret", expires_at)
    params = {
        dashboard.AUTH_QUERY_TOKEN: signature,
        dashboard.AUTH_QUERY_EXPIRES: str(expires_at),
    }

    monkeypatch.setattr(dashboard, "query_param_value", lambda name: params.get(name))

    assert dashboard.has_valid_auth_query(settings) is True


def test_build_query_preserves_auth_params(monkeypatch) -> None:
    dashboard = load_dashboard_module()
    params = {
        "section": dashboard.SECTION_OPTIONS[0],
        "currency": "USD",
        "provider": "全部",
        "asset": "全部",
        "view": dashboard.HOLDINGS_VIEW_OPTIONS[0],
        "sort": dashboard.HOLDINGS_SORT_OPTIONS[0],
        dashboard.AUTH_QUERY_TOKEN: "signed-token",
        dashboard.AUTH_QUERY_EXPIRES: "4102444800",
    }

    monkeypatch.setattr(dashboard, "query_param_value", lambda name: params.get(name))

    query = dashboard.build_query(section=dashboard.SECTION_OPTIONS[-1], currency="CNY")
    parsed = parse_qs(urlparse(query).query)

    assert parsed["section"] == [dashboard.SECTION_OPTIONS[-1]]
    assert parsed["currency"] == ["CNY"]
    assert parsed[dashboard.AUTH_QUERY_TOKEN] == ["signed-token"]
    assert parsed[dashboard.AUTH_QUERY_EXPIRES] == ["4102444800"]


def test_us_stock_symbols_only_include_ibkr_us_listed_positions() -> None:
    dashboard = load_dashboard_module()
    positions = pd.DataFrame(
        [
            {"provider": "IBKR", "asset_type": "stock", "currency": "USD", "symbol": "AAPL"},
            {"provider": "IBKR", "asset_type": "fund", "currency": "USD", "symbol": "QQQ"},
            {"provider": "HSBC China", "asset_type": "fund", "currency": "USD", "symbol": "IPFD2240"},
            {"provider": "CMB", "asset_type": "wealth", "currency": "USD", "symbol": "USD123"},
        ]
    )

    assert dashboard.us_stock_symbols_from_positions(positions) == ["AAPL", "QQQ"]
