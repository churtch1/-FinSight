from decimal import Decimal

from portfolio_mvp.fx import FxRate, convert_to_usd
from datetime import date


def test_convert_to_usd() -> None:
    rate = FxRate("CNY", "USD", Decimal("0.138"), date(2026, 4, 30), "manual")
    assert convert_to_usd(Decimal("100"), "CNY", rate) == Decimal("13.80")
    assert convert_to_usd(Decimal("100"), "USD", None) == Decimal("100")

