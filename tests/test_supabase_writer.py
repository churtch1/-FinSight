from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from portfolio_mvp.models import NormalizedRow
from portfolio_mvp.sync.supabase_writer import import_normalized_rows


@dataclass
class FakeResult:
    data: list[dict[str, Any]]


class FakeQuery:
    def __init__(self, client: FakeClient, table: str) -> None:
        self.client = client
        self.table = table
        self.action = "select"
        self.payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self.filters: list[tuple[str, Any]] = []

    def select(self, *_args: Any) -> FakeQuery:
        self.action = "select"
        return self

    def upsert(self, payload: dict[str, Any] | list[dict[str, Any]], **_kwargs: Any) -> FakeQuery:
        self.action = "upsert"
        self.payload = payload
        return self

    def insert(self, payload: dict[str, Any]) -> FakeQuery:
        self.action = "insert"
        self.payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self.filters.append((column, value))
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> FakeQuery:
        return self

    def limit(self, *_args: Any) -> FakeQuery:
        return self

    def execute(self) -> FakeResult:
        if self.action == "select":
            rows = self.client.rows.get(self.table, [])
            for column, value in self.filters:
                rows = [row for row in rows if row.get(column) == value]
            return FakeResult(rows)
        if self.action in {"insert", "upsert"}:
            assert isinstance(self.payload, dict)
            row = dict(self.payload)
            if "id" not in row:
                row["id"] = f"{self.table}-{len(self.client.rows.get(self.table, [])) + 1}"
            self.client.rows.setdefault(self.table, []).append(row)
            self.client.writes.append((self.table, self.action, row))
            return FakeResult([row])
        if self.action == "update":
            assert isinstance(self.payload, dict)
            self.client.writes.append((self.table, self.action, dict(self.payload)))
            return FakeResult([dict(self.payload)])
        raise AssertionError(f"Unsupported action: {self.action}")


class FakeClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "fx_rates": [
                {
                    "base_currency": "CNY",
                    "quote_currency": "USD",
                    "rate": "0.138",
                    "rate_date": "2026-04-30",
                    "source": "manual",
                }
            ]
        }
        self.writes: list[tuple[str, str, dict[str, Any]]] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def test_import_cash_balance_writes_cash_flow_and_position() -> None:
    client = FakeClient()
    row = NormalizedRow(
        account_name="HSBC China",
        provider="HSBC China",
        date=date(2026, 4, 30),
        type="cash_balance",
        instrument_code="CNY CASH",
        instrument_name="CNY Cash",
        isin="",
        asset_type="cash",
        quantity=Decimal("50000"),
        price=Decimal("1"),
        amount=Decimal("50000"),
        currency="CNY",
        fee=Decimal("0"),
        tax=Decimal("0"),
        description="Demo cash balance",
    )

    imported = import_normalized_rows(client, [row], "import-1")

    assert imported == 1
    cash_flow = [write for write in client.writes if write[0] == "cash_flows"][0][2]
    position = [write for write in client.writes if write[0] == "positions_current"][0][2]
    assert cash_flow["amount_usd"] == "6900.00"
    assert cash_flow["amount_cny"] == "50000.00"
    assert position["market_value_usd"] == "6900.00"
    assert position["market_value_cny"] == "50000.00"
    assert position["source_import_id"] == "import-1"
