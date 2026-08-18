from datetime import date
from decimal import Decimal

from types import SimpleNamespace

from portfolio_mvp.integrations.ibkr_flex import (
    FlexPosition,
    _reconcile_flex_account_snapshot,
    parse_flex_positions,
    sync_flex_positions,
)


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


def test_parse_flex_positions_includes_native_currency_ending_cash() -> None:
    xml = """
    <FlexQueryResponse>
      <FlexStatements>
        <FlexStatement accountId="U123" fromDate="20260816" toDate="20260817">
          <CashReport>
            <CashReportCurrency currency="BASE_SUMMARY" endingCash="9999.99" />
            <CashReportCurrency currency="USD" endingCash="456.78" />
            <CashReportCurrency currency="CNH" endingCash="123.45" />
          </CashReport>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """

    rows = parse_flex_positions(xml)

    assert [(row.account_id, row.symbol, row.quantity) for row in rows] == [
        ("U123", "USD CASH", Decimal("456.78")),
        ("U123", "CNH CASH", Decimal("123.45")),
    ]
    assert all(row.report_date == date(2026, 8, 17) for row in rows)
    assert all(row.asset_class == "CASH" for row in rows)


def test_sync_flex_positions_writes_cash_alongside_security() -> None:
    class Query:
        def __init__(self, client, table):
            self.client = client
            self.table = table
            self.payload = None

        def select(self, *_):
            return self

        def eq(self, *_):
            return self

        def update(self, payload):
            self.payload = payload
            return self

        def upsert(self, payload, on_conflict=None):
            self.payload = payload
            return self

        def execute(self):
            if self.payload is not None:
                if self.table == "positions_current":
                    self.client.writes.append(self.payload)
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=self.client.rows.get(self.table, []))

    class Client:
        def __init__(self):
            self.writes = []
            self.rows = {
                "accounts": [{"id": "account-1", "account_name": "U123", "account_number": None, "provider": "IBKR"}],
                "instruments": [
                    {"id": "usd-cash", "symbol": "USD CASH", "isin": None, "currency": "USD", "name": "USD Cash", "asset_type": "cash"},
                    {"id": "apple", "symbol": "AAPL", "isin": None, "currency": "USD", "name": "Apple", "asset_type": "stock"},
                ],
                "positions_current": [],
            }

        def table(self, name):
            return Query(self, name)

    common = {
        "account_id": "U123",
        "report_date": date(2026, 8, 17),
        "currency": "USD",
        "description": "",
        "conid": "",
        "security_id": "",
        "security_id_type": "",
        "cusip": "",
        "isin": "",
        "multiplier": Decimal("1"),
        "cost_basis_money": None,
        "unrealized_pnl": None,
        "accrued_interest": None,
    }
    positions = [
        FlexPosition(asset_class="CASH", symbol="USD CASH", quantity=Decimal("456.78"), mark_price=Decimal("1"), position_value=Decimal("456.78"), **common),
        FlexPosition(asset_class="STK", symbol="AAPL", quantity=Decimal("2"), mark_price=Decimal("220"), position_value=Decimal("440"), **common),
    ]
    client = Client()

    updated = sync_flex_positions(client, positions)

    assert updated == 2
    by_instrument = {row["instrument_id"]: row for row in client.writes}
    assert by_instrument["usd-cash"]["quantity"] == "456.78"
    assert by_instrument["usd-cash"]["market_value_original"] == "456.78"
    assert by_instrument["usd-cash"]["fx_rate_source"] == "ibkr_flex:cash"
    assert by_instrument["apple"]["quantity"] == "2"


def test_reconcile_flex_snapshot_closes_missing_security_and_missing_cash_currency() -> None:
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
        cash_reported=True,
    )

    assert {row["instrument_id"] for row in client.writes} == {"closed-etf", "cash"}
    closed = next(row for row in client.writes if row["instrument_id"] == "closed-etf")
    cash = next(row for row in client.writes if row["instrument_id"] == "cash")
    assert closed["quantity"] == "0"
    assert closed["market_value_original"] == "0"
    assert closed["fx_rate_source"] == "ibkr_flex:closed"
    assert cash["quantity"] == "0"
    assert cash["market_value_original"] == "0"
    assert cash["fx_rate_source"] == "ibkr_flex:cash_zero"
    assert cash["valuation_date"] == "2026-08-03"
