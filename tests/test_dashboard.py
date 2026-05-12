from __future__ import annotations

import importlib.util
from pathlib import Path
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
