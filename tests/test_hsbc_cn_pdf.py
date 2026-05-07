from __future__ import annotations

from datetime import date
from decimal import Decimal

from portfolio_mvp.parsers import hsbc_cn_pdf


def test_parse_hsbc_cn_pdf_extracts_cny_cash_balance(monkeypatch) -> None:
    sample_text = """
    汇丰银行（中国）财富管理报告
    账户号码: 6222-****-8888
    报告日期: 2026年05月06日
    总资产合计 CNY 1,234,567.89
    """
    monkeypatch.setattr(hsbc_cn_pdf, "extract_text", lambda _: sample_text)

    rows = hsbc_cn_pdf.parse_hsbc_cn_pdf("dummy.pdf")

    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "HSBC China"
    assert row.account_name == "6222-****-8888"
    assert row.date == date(2026, 5, 6)
    assert row.type == "cash_balance"
    assert row.amount == Decimal("1234567.89")
    assert row.currency == "CNY"


def test_parse_hsbc_cn_pdf_extracts_allocation_rows(monkeypatch) -> None:
    sample_text = """
    资产配置报告
    2026 年 05 月 07 日
    汇丰新可能 CNHSBC517081956
    产品配置情况
    总资产 ( 不含在途资金 ):人民币 516,350.30
    您的持仓分布情况
    基金相关产品 (31.93%)
    CNY 164,847.50
    理财产品 (39.20%)
    CNY 202,411.72
    现金 / 存款 (28.87%)
    CNY 149,091.09
    """
    monkeypatch.setattr(hsbc_cn_pdf, "extract_text", lambda _: sample_text)

    rows = hsbc_cn_pdf.parse_hsbc_cn_pdf("dummy.pdf")

    assert [row.instrument_name for row in rows] == ["基金相关产品", "理财产品", "现金 / 存款"]
    assert [row.type for row in rows] == ["position_snapshot", "position_snapshot", "position_snapshot"]
    assert [row.asset_type for row in rows] == ["fund", "wealth_product", "cash"]
    assert [row.amount for row in rows] == [Decimal("164847.50"), Decimal("202411.72"), Decimal("149091.09")]
    assert rows[0].date == date(2026, 5, 7)
    assert rows[0].account_name == "CNHSBC517081956"


def test_parse_hsbc_cn_pdf_extracts_product_detail_rows(monkeypatch) -> None:
    sample_text = """
    资产配置报告
    2026 年 05 月 07 日
    汇丰新可能 CNHSBC517081956
    您的持仓分布情况
    基金相关产品 (31.93%)
    CNY 164,847.50
    理财产品 (39.20%)
    CNY 202,411.72
    现金 / 存款 (28.87%)
    CNY 149,091.09
    基金相关产品
    市值 成本 未实现资本损益 现金分红收益 总收益
    价格日期: 2026/05/06
    人民币
    30,850.35
    23,503.2400 份 @ 人民币
    1.3126
    人民币
    30,000.00
    人民币
    +850.35
    +2.84%
    人民币
    1,222.17
    人民币
    +2,072.52
    +6.91%
    [ 仅电子渠道 ] 易方达中证红利 ETF 联接 C ( 009052)
    资管计划及信托计划
    理财产品
    市值 成本 未实现资本损益 现金分红收益 总收益
    价格日期: 2026/04/30
    人民币
    202,411.72
    191,405.8800 份 @ 人民币
    1.0575
    人民币
    200,000.00
    人民币
    +2,411.72
    +1.21%
    人民币
    0.00
    人民币
    +2,411.72
    +1.21%
    平安理财灵活成长汇稳 28 天持有 A ( LWCG02801A)
    您的持仓详情 —— 保险产品
    """
    monkeypatch.setattr(hsbc_cn_pdf, "extract_text", lambda _: sample_text)

    rows = hsbc_cn_pdf.parse_hsbc_cn_pdf("dummy.pdf")

    assert [row.instrument_name for row in rows] == [
        "[ 仅电子渠道 ] 易方达中证红利 ETF 联接 C ( 009052)",
        "平安理财灵活成长汇稳 28 天持有 A ( LWCG02801A)",
        "现金 / 存款",
    ]
    assert rows[0].instrument_code == "009052"
    assert rows[0].asset_type == "fund"
    assert rows[0].cost == Decimal("30000.00")
    assert rows[0].income == Decimal("1222.17")
    assert rows[0].total_pnl == Decimal("2072.52")
    assert rows[1].instrument_code == "LWCG02801A"
    assert rows[1].asset_type == "wealth_product"
    assert rows[1].unrealized_pnl == Decimal("2411.72")
    assert rows[2].asset_type == "cash"
