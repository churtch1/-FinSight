from __future__ import annotations

from types import SimpleNamespace

from portfolio_mvp.db import _select_all


class FakeQuery:
    def __init__(self, rows: list[dict[str, int]]) -> None:
        self.rows = rows
        self.ranges: list[tuple[int, int]] = []

    def select(self, _columns: str) -> "FakeQuery":
        return self

    def order(self, _column: str, *, desc: bool) -> "FakeQuery":
        return self

    def range(self, start: int, end: int) -> "FakeQuery":
        self.ranges.append((start, end))
        self.current_range = (start, end)
        return self

    def execute(self) -> SimpleNamespace:
        start, end = self.current_range
        return SimpleNamespace(data=self.rows[start : end + 1])


class FakeClient:
    def __init__(self, rows: list[dict[str, int]]) -> None:
        self.query = FakeQuery(rows)

    def table(self, _name: str) -> FakeQuery:
        return self.query


def test_select_all_reads_past_supabase_default_page_size() -> None:
    expected = [{"id": index} for index in range(1407)]
    client = FakeClient(expected)

    actual = _select_all(
        client,
        "positions_current",
        order_by=(("valuation_date", False), ("id", False)),
    )

    assert actual == expected
    assert client.query.ranges == [(0, 999), (1000, 1999)]
