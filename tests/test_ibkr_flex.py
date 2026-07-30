from datetime import date
from decimal import Decimal

from portfolio_mvp.integrations.ibkr_flex import parse_flex_positions


def test_parse_flex_positions_reads_bond_mark_and_identifiers() -> None:
    xml = """
    <FlexQueryResponse>
      <FlexStatements>
        <FlexStatement accountId="U123" fromDate="20260729" toDate="20260729">
          <OpenPositions>
            <OpenPosition accountId="U123" reportDate="20260729" assetCategory="BOND"
              currency="USD" symbol="US-T" description="US Treasury Note"
              conid="854486561" securityID="91282ABC1" securityIDType="CUSIP"
              cusip="91282ABC1" isin="US91282ABC12" position="12000" multiplier="1"
              markPrice="96.875" positionValue="11625.00" costBasisMoney="11200.00"
              fifoPnlUnrealized="425.00" accruedInterest="73.42" />
          </OpenPositions>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """

    rows = parse_flex_positions(xml)

    assert len(rows) == 1
    assert rows[0].report_date == date(2026, 7, 29)
    assert rows[0].conid == "854486561"
    assert rows[0].cusip == "91282ABC1"
    assert rows[0].mark_price == Decimal("96.875")
    assert rows[0].position_value == Decimal("11625.00")
    assert rows[0].accrued_interest == Decimal("73.42")
