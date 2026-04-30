from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio_mvp.models import NormalizedRow
from portfolio_mvp.repositories.accounts import upsert_account
from portfolio_mvp.repositories.fx_rates import convert_amount, load_fx_rows
from portfolio_mvp.repositories.imports import log_import_error
from portfolio_mvp.repositories.instruments import resolve_instrument

if TYPE_CHECKING:
    from supabase import Client


def import_normalized_rows(client: "Client", rows: list[NormalizedRow], import_id: str) -> int:
    fx_rows = load_fx_rows(client)
    count = 0
    for index, row in enumerate(rows, start=1):
        try:
            _import_normalized_row(client, row, import_id, fx_rows)
            count += 1
        except Exception as exc:
            log_import_error(client, import_id, index, row.__dict__, str(exc))
    return count


def _import_normalized_row(client: "Client", row: NormalizedRow, import_id: str, fx_rows: list[dict]) -> None:
    currency = row.currency.upper()
    base_currency = "USD" if row.provider.upper() == "IBKR" else currency
    account_type = "brokerage" if row.provider.upper() == "IBKR" else "bank"
    account_id = upsert_account(client, row.provider, row.account_name, base_currency, account_type=account_type)
    instrument_id = resolve_instrument(
        client,
        row.instrument_code,
        row.instrument_name,
        row.isin,
        currency,
        row.asset_type,
        provider=row.provider,
    )

    usd = convert_amount(row.amount, currency, "USD", fx_rows)
    cny = convert_amount(row.amount, currency, "CNY", fx_rows)
    common_fx = {
        "fx_rate_to_usd": str(usd.rate) if usd.rate is not None else None,
        "fx_rate_to_cny": str(cny.rate) if cny.rate is not None else None,
        "fx_rate_source": usd.source or cny.source,
        "fx_rate_date": (usd.rate_date or cny.rate_date).isoformat() if (usd.rate_date or cny.rate_date) else None,
    }
    amount_values = {
        "amount_usd": str(usd.value) if usd.value is not None else None,
        "amount_cny": str(cny.value) if cny.value is not None else None,
    }
    position_values = {
        "market_value_usd": str(usd.value) if usd.value is not None else None,
        "market_value_cny": str(cny.value) if cny.value is not None else None,
    }

    if row.type == "position_snapshot":
        client.table("positions_current").upsert(
            {
                "account_id": account_id,
                "instrument_id": instrument_id,
                "quantity": str(row.quantity),
                "price_original": str(row.price),
                "market_value_original": str(row.amount),
                "currency": currency,
                "valuation_date": row.date.isoformat(),
                "source": row.provider,
                "source_import_id": import_id,
                **position_values,
                **common_fx,
            },
            on_conflict="account_id,instrument_id,valuation_date",
        ).execute()
        return

    if row.type in {"deposit", "withdrawal", "cash_balance"}:
        client.table("cash_flows").insert(
            {
                "source_import_id": import_id,
                "account_id": account_id,
                "flow_date": row.date.isoformat(),
                "flow_type": row.type,
                "amount_original": str(row.amount),
                "currency": currency,
                "description": row.description,
                **amount_values,
                **common_fx,
            }
        ).execute()
        if row.type == "cash_balance":
            _upsert_cash_position(client, row, import_id, account_id, currency, position_values, common_fx)
        return

    if row.type in {"dividend", "interest", "coupon"}:
        client.table("income_records").insert(
            {
                "source_import_id": import_id,
                "account_id": account_id,
                "instrument_id": instrument_id,
                "income_date": row.date.isoformat(),
                "income_type": row.type,
                "amount_original": str(row.amount),
                "currency": currency,
                "description": row.description,
                **amount_values,
                **common_fx,
            }
        ).execute()
        return

    transaction_type = row.type if row.type else "other"
    client.table("transactions").insert(
        {
            "source_import_id": import_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "transaction_date": row.date.isoformat(),
            "transaction_type": transaction_type,
            "quantity": str(row.quantity),
            "price_original": str(row.price),
            "amount_original": str(row.amount),
            "currency": currency,
            "fee_original": str(row.fee),
            "tax_original": str(row.tax),
            "description": row.description,
            **amount_values,
            **common_fx,
        }
    ).execute()


def _upsert_cash_position(
    client: "Client",
    row: NormalizedRow,
    import_id: str,
    account_id: str,
    currency: str,
    position_values: dict[str, str | None],
    common_fx: dict[str, str | None],
) -> None:
    cash_instrument_id = resolve_instrument(
        client,
        f"{currency} CASH",
        f"{currency} Cash",
        "",
        currency,
        "cash",
        provider=row.provider,
    )
    client.table("positions_current").upsert(
        {
            "account_id": account_id,
            "instrument_id": cash_instrument_id,
            "quantity": str(row.amount),
            "price_original": "1",
            "market_value_original": str(row.amount),
            "currency": currency,
            "valuation_date": row.date.isoformat(),
            "source": row.provider,
            "source_import_id": import_id,
            **position_values,
            **common_fx,
        },
        on_conflict="account_id,instrument_id,valuation_date",
    ).execute()

