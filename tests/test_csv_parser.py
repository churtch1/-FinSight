from pathlib import Path

from portfolio_mvp.parsers.csv_normalized import parse_csv


def test_parse_sample_csv() -> None:
    rows = parse_csv(Path("sample_data/transactions_template.csv"))
    assert len(rows) == 5
    assert rows[0].instrument_code == "NVDA"
    assert rows[3].asset_type == "wealth_product"

