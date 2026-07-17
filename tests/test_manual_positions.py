from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from portfolio_mvp.fund_nav import FundNav
from portfolio_mvp.parsers.manual_positions import normalize_manual_instrument_name, parse_manual_position_records


def test_parse_manual_position_records_builds_snapshot_rows() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_code": "161725",
                "instrument_name": "CMB Fund",
                "asset_type": "fund",
                "quantity": "100",
                "price": "1.25",
                "amount": "",
                "currency": "CNY",
                "cost": "100.00",
                "unrealized_pnl": "25.00",
                "total_pnl": "25.00",
                "description": "manual snapshot",
            }
        ],
        provider="CMB",
        account_name="CMB Manual",
        valuation_date=date(2026, 5, 13),
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "CMB"
    assert row.account_name == "CMB Manual"
    assert row.type == "position_snapshot"
    assert row.instrument_code == "161725"
    assert row.asset_type == "fund"
    assert row.quantity == Decimal("100")
    assert row.price == Decimal("1.25")
    assert row.amount == Decimal("125.00")
    assert row.cost == Decimal("100.00")
    assert row.total_pnl == Decimal("25.00")


def test_parse_manual_position_records_uses_amount_when_quantity_is_blank() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_name": "YuEBao",
                "asset_type": "cash",
                "amount": "12,345.67",
                "currency": "",
            }
        ],
        provider="Alipay",
        account_name="Alipay Manual",
        valuation_date=date(2026, 5, 13),
    )

    assert rows[0].quantity == Decimal("1")
    assert rows[0].price == Decimal("12345.670000")
    assert rows[0].amount == Decimal("12345.67")
    assert rows[0].currency == "CNY"


def test_parse_manual_position_records_infers_fund_quantity_from_nav_and_total_pnl() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_code": "270023",
                "instrument_name": "GF Global Select",
                "asset_type": "fund",
                "amount": "2345.60",
                "currency": "CNY",
                "total_pnl": "345.60",
            }
        ],
        provider="Alipay",
        account_name="Alipay Manual",
        valuation_date=date(2026, 5, 13),
        fund_navs={
            "270023": FundNav(
                fund_code="270023",
                fund_name="GF Global Select",
                unit_nav=Decimal("2.3456"),
                nav_date=date(2026, 5, 11),
            )
        },
    )

    row = rows[0]
    assert row.quantity == Decimal("1000.000000")
    assert row.price == Decimal("2.3456")
    assert row.quantity_source == "inferred"
    assert row.cost == Decimal("2000.00")
    assert row.total_pnl == Decimal("345.60")


def test_parse_manual_position_records_computes_price_from_quantity_and_amount() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_name": "CMB Gold",
                "asset_type": "gold",
                "quantity": "56.8673",
                "amount": "58555.69",
                "currency": "CNY",
                "total_pnl": "13405.69",
            }
        ],
        provider="CMB",
        account_name="CMB Manual",
        valuation_date=date(2026, 5, 13),
    )

    row = rows[0]
    assert row.quantity == Decimal("56.8673")
    assert row.price == Decimal("1029.689998")
    assert row.cost == Decimal("45150.00")


def test_parse_manual_position_records_uses_holding_pnl_for_gold_cost() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_name": "招行黄金账户",
                "asset_type": "gold",
                "quantity": "56.8673",
                "amount": "58,555.69",
                "currency": "CNY",
                "unrealized_pnl": "13,405.69",
                "total_pnl": "18,996.10",
                "description": "累计收益 18,996.10",
            }
        ],
        provider="CMB",
        account_name="CMB Manual",
        valuation_date=date(2026, 5, 21),
    )

    row = rows[0]
    assert row.asset_type == "gold"
    assert row.quantity == Decimal("56.8673")
    assert row.amount == Decimal("58555.69")
    assert row.price == Decimal("1029.689998")
    assert row.cost == Decimal("45150.00")
    assert row.unrealized_pnl == Decimal("13405.69")
    assert row.total_pnl == Decimal("13405.69")


def test_parse_manual_position_records_preserves_usd_wealth_product() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_code": "CMB-USD-001",
                "instrument_name": "CMB USD Wealth Product",
                "asset_type": "wealth_product",
                "quantity": "1",
                "amount": "10,000.00",
                "currency": "USD",
                "cost": "9,900.00",
                "total_pnl": "100.00",
            }
        ],
        provider="CMB",
        account_name="CMB Manual",
        valuation_date=date(2026, 5, 21),
    )

    row = rows[0]
    assert row.asset_type == "wealth_product"
    assert row.amount == Decimal("10000.00")
    assert row.currency == "USD"
    assert row.cost == Decimal("9900.00")
    assert row.total_pnl == Decimal("100.00")


def test_parse_manual_position_records_can_infer_cost_from_return_rate() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_name": "Fund without PnL amount",
                "asset_type": "fund",
                "amount": "32842.91",
                "currency": "CNY",
                "pnl_pct": "64.21%",
            }
        ],
        provider="Alipay",
        account_name="Alipay Manual",
        valuation_date=date(2026, 5, 13),
    )

    assert rows[0].cost == Decimal("20000.55")
    assert rows[0].total_pnl == Decimal("12842.36")


def test_parse_manual_position_records_can_infer_amount_from_pnl_and_return_rate() -> None:
    rows = parse_manual_position_records(
        [
            {
                "instrument_name": "广发纳斯达克100ETF联接(QDII)A",
                "asset_type": "fund",
                "amount": "",
                "currency": "CNY",
                "total_pnl": "3,262.55",
                "pnl_pct": "49.43%",
            }
        ],
        provider="Alipay",
        account_name="Alipay Manual",
        valuation_date=date(2026, 7, 10),
    )

    assert rows[0].amount == Decimal("9862.89")
    assert rows[0].cost == Decimal("6600.34")
    assert rows[0].total_pnl == Decimal("3262.55")


def test_normalize_manual_instrument_name_truncates_wealth_holding_suffix() -> None:
    wealth_name = "\u591a\u6708\u5b9d \u62db\u94f6\u7406\u8d22\u5609\u76c8(\u7a33\u91d1)\u4e00\u5e74\u6301\u6709\u65e5\u5f00..."
    normalized_name = "\u591a\u6708\u5b9d \u62db\u94f6\u7406\u8d22\u5609\u76c8(\u7a33\u91d1)\u4e00\u5e74\u6301\u6709"
    assert normalize_manual_instrument_name(wealth_name, "wealth_product") == normalized_name
    assert normalize_manual_instrument_name(wealth_name, "fund") == wealth_name


def test_parse_manual_position_records_rejects_blank_instrument() -> None:
    with pytest.raises(ValueError, match="instrument_code or instrument_name is required"):
        parse_manual_position_records(
            [{"amount": "100", "currency": "CNY"}],
            provider="CMB",
            account_name="CMB Manual",
            valuation_date=date(2026, 5, 13),
        )
