from __future__ import annotations

from portfolio_mvp.repositories.accounts import upsert_account
from portfolio_mvp.repositories.common import file_sha256, json_safe as _json_safe
from portfolio_mvp.repositories.fx_rates import load_fx_rows, latest_rate_for_pair
from portfolio_mvp.repositories.imports import complete_import, create_import_record, log_import_error
from portfolio_mvp.repositories.instruments import resolve_instrument
from portfolio_mvp.sync.supabase_writer import import_normalized_rows

__all__ = [
    "_json_safe",
    "complete_import",
    "create_import_record",
    "file_sha256",
    "import_normalized_rows",
    "load_fx_rows",
    "log_import_error",
    "rate_for_currency",
    "resolve_instrument",
    "upsert_account",
]


def rate_for_currency(currency: str, fx_rows: list[dict]) -> object:
    return latest_rate_for_pair(currency, "USD", fx_rows)
