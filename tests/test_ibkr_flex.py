from datetime import date
from decimal import Decimal

from types import SimpleNamespace

from portfolio_mvp.integrations.ibkr_flex import _reconcile_flex_account_snapshot, parse_flex_positions


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


def test_reconcile_flex_snapshot_closes_missing_security_and_carries_cash() -> None:
    rows = [
        {
            "account_id": "account-1",
            "instrument_id": "open-stock",
            "quantity": "2",
            "market_value_original": "200",
            "currency": "USD",
            "valuation_date": "2026-08-03",
            "instruments": {"asset_type": "stock"},
        },
        {
            "account_id": "account-1",
            "instrument_id": "closed-etf",
            "quantity": "49",
            "market_value_original": "4900",
            "market_value_usd": "4900",
            "currency": "USD",
            "valuation_date": "2026-07-31",
            "cost_original": "4800",
            "instruments": {"asset_type": "stock"},
        },
        {
            "account_id": "account-1",
            "instrument_id": "cash",
            "quantity": "1000",
            "market_value_original": "1000",
            "currency": "USD",
            "valuation_date": "2026-07-31",
            "instruments": {"asset_type": "cash"},
        },
    ]

    class Query:
        def __init__(self, client):
            self.client = client
            self.payload = None

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def upsert(self, payload, on_conflict=None):
            self.payload = payload
            return self

        def execute(self):
            if self.payload is not None:
                self.client.writes.append(self.payload)
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=self.client.rows)

    class Client:
        def __init__(self):
            self.rows = rows
            self.writes = []

        def table(self, name):
            assert name == "positions_current"
            return Query(self)

    client = Client()
    _reconcile_flex_account_snapshot(
        client,
        account_uuid="account-1",
        report_date=date(2026, 8, 3),
        open_instrument_ids={"open-stock"},
    )

    assert {row["instrument_id"] for row in client.writes} == {"closed-etf", "cash"}
    closed = next(row for row in client.writes if row["instrument_id"] == "closed-etf")
    cash = next(row for row in client.writes if row["instrument_id"] == "cash")
    assert closed["quantity"] == "0"
    assert closed["market_value_original"] == "0"
    assert closed["fx_rate_source"] == "ibkr_flex:closed"
    assert cash["quantity"] == "1000"
    assert cash["valuation_date"] == "2026-08-03"
