from datetime import datetime
from types import SimpleNamespace

import pytest

from portfolio_mvp.config import Settings
from portfolio_mvp.integrations.ibkr import sync_ibkr_data


class FakeIB:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    def connect(self, host: str, port: int, clientId: int, timeout: int) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def managedAccounts(self) -> list[str]:
        return ["DU123"]

    def accountSummary(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(account="DU123", tag="BaseCurrency", value="USD", currency=""),
            SimpleNamespace(account="DU123", tag="NetLiquidation", value="15000", currency="USD"),
        ]

    def portfolio(self) -> list[SimpleNamespace]:
        contract = SimpleNamespace(symbol="AAPL", localSymbol="AAPL", conId=265598, secType="STK", currency="USD")
        return [
            SimpleNamespace(
                account="DU123",
                contract=contract,
                position=10,
                marketPrice=190.25,
                marketValue=1902.50,
            )
        ]

    def accountValues(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(account="DU123", tag="CashBalance", value="1000.25", currency="USD"),
            SimpleNamespace(account="DU123", tag="TotalCashBalance", value="1000.25", currency="USD"),
            SimpleNamespace(account="DU123", tag="CashBalance", value="8000", currency="HKD"),
            SimpleNamespace(account="DU123", tag="CashBalance", value="0", currency="CNY"),
        ]

    def reqExecutions(self) -> list[SimpleNamespace]:
        contract = SimpleNamespace(symbol="AAPL", localSymbol="AAPL", conId=265598, secType="STK", currency="USD")
        execution = SimpleNamespace(
            acctNumber="DU123",
            shares=2,
            price=188.5,
            side="BOT",
            time=datetime(2026, 4, 30, 9, 30),
            execId="0001",
        )
        return [SimpleNamespace(contract=contract, execution=execution)]


def test_sync_ibkr_data_normalizes_positions_cash_and_executions() -> None:
    fake = FakeIB()

    data = sync_ibkr_data(
        account="all",
        settings=Settings(ibkr_host="127.0.0.1", ibkr_port=7497, ibkr_client_id=11),
        ib_factory=lambda: fake,
    )

    assert fake.connected is True
    assert fake.disconnected is True
    assert data.accounts == ["DU123"]
    assert data.account_summaries["DU123"]["BaseCurrency"] == "USD"

    position_rows = [row for row in data.rows if row.type == "position_snapshot"]
    cash_rows = [row for row in data.rows if row.type == "cash_balance"]
    execution_rows = [row for row in data.rows if row.type == "buy"]

    assert len(position_rows) == 1
    assert position_rows[0].instrument_code == "AAPL"
    assert position_rows[0].asset_type == "stock"

    assert sorted(row.currency for row in cash_rows) == ["HKD", "USD"]
    assert {row.instrument_code for row in cash_rows} == {"HKD CASH", "USD CASH"}

    assert len(execution_rows) == 1
    assert execution_rows[0].amount == execution_rows[0].quantity * execution_rows[0].price


def test_sync_ibkr_data_rejects_unknown_account() -> None:
    with pytest.raises(RuntimeError, match="IBKR account not found"):
        sync_ibkr_data(
            account="DU999",
            settings=Settings(),
            ib_factory=FakeIB,
        )
