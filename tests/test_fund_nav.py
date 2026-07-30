from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_mvp.fund_nav import (
    latest_nav_map,
    normalize_fund_code,
    parse_offshore_fund_page,
    parse_eastmoney_nav_response,
    parse_eastmoney_pingzhongdata_response,
    parse_fund_nav_csv,
)


def test_parse_eastmoney_nav_response_reads_disclosed_nav() -> None:
    text = 'jsonpgz({"fundcode":"270023","name":"GF Global Select","jzrq":"2026-05-11","dwjz":"2.3456","ljjz":"2.7890","gztime":"2026-05-12 15:00"});'

    nav = parse_eastmoney_nav_response("270023", text)

    assert nav.fund_code == "270023"
    assert nav.fund_name == "GF Global Select"
    assert nav.unit_nav == Decimal("2.3456")
    assert nav.accumulated_nav == Decimal("2.7890")
    assert nav.nav_date == date(2026, 5, 11)
    assert nav.status == "ok"


def test_parse_eastmoney_nav_response_rejects_empty_nav() -> None:
    text = 'jsonpgz({"fundcode":"270023","name":"GF Global Select","jzrq":"2026-05-11","dwjz":""});'

    with pytest.raises(ValueError, match="Fund NAV is missing"):
        parse_eastmoney_nav_response("270023", text)


def test_parse_eastmoney_pingzhongdata_response_reads_latest_trend_nav() -> None:
    text = """
    var fS_name = "华夏标普500ETF发起式联接(QDII)A(人民币)";
    var fS_code = "018064";
    var Data_netWorthTrend = [{"x":1783526400000,"y":1.6932},{"x":1783612800000,"y":1.6964}];
    """

    nav = parse_eastmoney_pingzhongdata_response("018064", text)

    assert nav.fund_code == "018064"
    assert nav.fund_name == "华夏标普500ETF发起式联接(QDII)A(人民币)"
    assert nav.unit_nav == Decimal("1.6964")
    assert nav.source == "eastmoney_pingzhongdata"


def test_latest_nav_map_keeps_latest_ok_row() -> None:
    rows = [
        {"fund_code": "270023", "fund_name": "old", "unit_nav": "2.1", "nav_date": "2026-05-10", "source": "manual", "status": "ok"},
        {"fund_code": "270023", "fund_name": "new", "unit_nav": "2.2", "nav_date": "2026-05-11", "source": "manual", "status": "ok"},
        {"fund_code": "000001", "fund_name": "bad", "unit_nav": "1.0", "nav_date": "2026-05-11", "source": "manual", "status": "error"},
    ]

    navs = latest_nav_map(rows)

    assert navs["270023"].fund_name == "new"
    assert "000001" not in navs


def test_parse_fund_nav_csv() -> None:
    csv_path = Path("sample_data/fund_navs_demo.csv")

    navs = parse_fund_nav_csv(csv_path)

    assert len(navs) == 1
    assert navs[0].fund_code == "270023"
    assert navs[0].unit_nav == Decimal("2.3456")


def test_normalize_fund_code_accepts_hsbc_offshore_code() -> None:
    assert normalize_fund_code("OIP fund (ipfd3391)") == "IPFD3391"


def test_parse_offshore_fund_page_reads_iso_daily_nav() -> None:
    text = "<h1>Fund</h1><div>NAV USD 333.33</div><div>As of 2026-07-24</div>"

    unit_nav, nav_date = parse_offshore_fund_page(text)

    assert unit_nav == Decimal("333.33")
    assert nav_date == date(2026, 7, 24)


def test_parse_offshore_fund_page_reads_european_daily_nav_date() -> None:
    text = "<div>NAV 254.12 USD</div><div>NAV date 22/07/2026</div>"

    unit_nav, nav_date = parse_offshore_fund_page(text)

    assert unit_nav == Decimal("254.12")
    assert nav_date == date(2026, 7, 22)


def test_parse_offshore_fund_page_reads_embedded_daily_series() -> None:
    text = (
        '<div data-chart=\'{"data":[{"period":"27\\/07","value":250.72},'
        '{"period":"28\\/07","value":251.78}]}\'></div>'
    )

    unit_nav, nav_date = parse_offshore_fund_page(text)

    assert unit_nav == Decimal("251.78")
    assert (nav_date.month, nav_date.day) == (7, 28)
