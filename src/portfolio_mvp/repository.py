from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from supabase import Client

from portfolio_mvp.fx import FxRate, convert_to_usd, latest_rate_from_rows
from portfolio_mvp.models import NormalizedRow, normalize_asset_type


POSITION_METRIC_COLUMNS = "cost_original,unrealized_pnl_original,income_original,total_pnl_original,pnl_pct"
_POSITION_METRICS_SUPPORTED: bool | None = None


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upsert_account(client: Client, provider: str, account_name: str, base_currency: str) -> str:
    payload = {
        "provider": provider,
        "account_name": account_name,
        "base_currency": base_currency.upper(),
    }
    client.table("accounts").upsert(payload, on_conflict="provider,account_name").execute()
    rows = client.table("accounts").select("id").eq("provider", provider).eq("account_name", account_name).limit(1).execute().data
    return rows[0]["id"]


def resolve_instrument(
    client: Client,
    code: str,
    name: str,
    isin: str,
    currency: str,
    asset_type: str,
) -> str:
    code = (code or "").strip()
    name = (name or code or "Unknown").strip()
    isin = (isin or "").strip()
    alias = code or isin or name

    if alias:
        alias_rows = client.table("instrument_aliases").select("instrument_id").eq("alias", alias).limit(1).execute().data
        if alias_rows:
            return alias_rows[0]["instrument_id"]

    normalized_asset_type = normalize_asset_type(asset_type)
    query = client.table("instruments").select("id,asset_type")
    if isin:
        rows = query.eq("isin", isin).limit(1).execute().data
    elif code:
        rows = query.eq("symbol", code).eq("currency", currency.upper()).limit(1).execute().data
    else:
        rows = query.eq("name", name).eq("currency", currency.upper()).limit(1).execute().data
    if rows:
        instrument_id = rows[0]["id"]
        existing_asset_type = normalize_asset_type(rows[0].get("asset_type"))
        if existing_asset_type == "other" and normalized_asset_type != "other":
            client.table("instruments").update({"asset_type": normalized_asset_type}).eq("id", instrument_id).execute()
    else:
        payload = {
            "symbol": code or None,
            "name": name,
            "isin": isin or None,
            "currency": currency.upper(),
            "asset_type": normalized_asset_type,
            "mapping_status": "confirmed" if code or isin else "needs_review",
        }
        instrument_id = client.table("instruments").insert(payload).execute().data[0]["id"]

    if alias:
        client.table("instrument_aliases").upsert(
            {"instrument_id": instrument_id, "alias": alias, "alias_type": "auto"},
            on_conflict="alias",
        ).execute()
    return instrument_id


def create_import_record(client: Client, source: str, source_type: str, file_name: str | None = None, file_hash: str | None = None) -> str:
    payload = {
        "source": source,
        "source_type": source_type,
        "file_name": file_name,
        "file_hash": file_hash,
        "status": "started",
    }
    data = client.table("statement_imports").upsert(payload, on_conflict="source,file_hash").execute().data
    if data:
        return data[0]["id"]
    rows = client.table("statement_imports").select("id").eq("source", source).eq("file_hash", file_hash).limit(1).execute().data
    return rows[0]["id"]


def complete_import(client: Client, import_id: str, rows_imported: int, status: str = "completed", error_summary: str | None = None) -> None:
    client.table("statement_imports").update(
        {"status": status, "rows_imported": rows_imported, "error_summary": error_summary}
    ).eq("id", import_id).execute()


def log_import_error(client: Client, import_id: str, row_number: int | None, raw_payload: dict[str, Any] | None, message: str) -> None:
    client.table("import_errors").insert(
        {
            "statement_import_id": import_id,
            "row_number": row_number,
            "raw_payload": _json_safe(raw_payload or {}),
            "error_message": message,
        }
    ).execute()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def load_fx_rows(client: Client) -> list[dict[str, Any]]:
    return client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []


def rate_for_currency(currency: str, fx_rows: list[dict[str, Any]]) -> FxRate | None:
    return latest_rate_from_rows(currency, fx_rows)


def import_normalized_rows(client: Client, rows: list[NormalizedRow], import_id: str) -> int:
    fx_rows = load_fx_rows(client)
    supports_position_metrics = position_metrics_supported(client)
    account_cache: dict[tuple[str, str], str] = {}
    _clear_existing_snapshot_positions(client, rows, account_cache)
    count = 0
    for index, row in enumerate(rows, start=1):
        try:
            currency = row.currency.upper()
            base_currency = "USD" if row.provider.upper() == "IBKR" else currency
            account_key = (row.provider, row.account_name)
            account_id = account_cache.get(account_key)
            if account_id is None:
                account_id = upsert_account(client, row.provider, row.account_name, base_currency)
                account_cache[account_key] = account_id
            instrument_id = resolve_instrument(
                client,
                row.instrument_code,
                row.instrument_name,
                row.isin,
                currency,
                row.asset_type,
            )
            fx_rate = rate_for_currency(currency, fx_rows)
            amount_usd = convert_to_usd(row.amount, currency, fx_rate)
            common_fx = {
                "fx_rate_to_usd": str(fx_rate.rate) if fx_rate else None,
                "fx_rate_source": fx_rate.source if fx_rate else None,
                "fx_rate_date": fx_rate.rate_date.isoformat() if fx_rate else None,
            }

            if row.type == "position_snapshot":
                market_value_usd = convert_to_usd(row.amount, currency, fx_rate)
                position_payload = {
                    "account_id": account_id,
                    "instrument_id": instrument_id,
                    "quantity": str(row.quantity),
                    "price_original": str(row.price),
                    "market_value_original": str(row.amount),
                    "currency": currency,
                    "market_value_usd": str(market_value_usd) if market_value_usd is not None else None,
                    "valuation_date": row.date.isoformat(),
                    **common_fx,
                }
                if supports_position_metrics:
                    position_payload.update(_position_metric_payload(row))
                client.table("positions_current").upsert(
                    position_payload,
                    on_conflict="account_id,instrument_id,valuation_date",
                ).execute()
            elif row.type in {"deposit", "withdrawal", "cash_balance"}:
                client.table("cash_flows").insert(
                    {
                        "statement_import_id": import_id,
                        "account_id": account_id,
                        "flow_date": row.date.isoformat(),
                        "flow_type": row.type,
                        "amount_original": str(row.amount),
                        "currency": currency,
                        "amount_usd": str(amount_usd) if amount_usd is not None else None,
                        "description": row.description,
                        **common_fx,
                    }
                ).execute()
                if row.type == "cash_balance":
                    cash_instrument_id = resolve_instrument(client, f"{currency} CASH", f"{currency} Cash", "", currency, "cash")
                    client.table("positions_current").upsert(
                        {
                            "account_id": account_id,
                            "instrument_id": cash_instrument_id,
                            "quantity": str(row.amount),
                            "price_original": "1",
                            "market_value_original": str(row.amount),
                            "currency": currency,
                            "market_value_usd": str(amount_usd) if amount_usd is not None else None,
                            "valuation_date": row.date.isoformat(),
                            **common_fx,
                        },
                        on_conflict="account_id,instrument_id,valuation_date",
                    ).execute()
            elif row.type in {"dividend", "interest"}:
                client.table("dividends_interest").insert(
                    {
                        "statement_import_id": import_id,
                        "account_id": account_id,
                        "instrument_id": instrument_id,
                        "income_date": row.date.isoformat(),
                        "income_type": row.type,
                        "amount_original": str(row.amount),
                        "currency": currency,
                        "amount_usd": str(amount_usd) if amount_usd is not None else None,
                        "description": row.description,
                        **common_fx,
                    }
                ).execute()
            elif row.type in {"fee", "tax"}:
                client.table("fees_taxes").insert(
                    {
                        "statement_import_id": import_id,
                        "account_id": account_id,
                        "fee_date": row.date.isoformat(),
                        "fee_type": row.type,
                        "amount_original": str(row.amount),
                        "currency": currency,
                        "amount_usd": str(amount_usd) if amount_usd is not None else None,
                        "description": row.description,
                        **common_fx,
                    }
                ).execute()
            else:
                client.table("transactions").insert(
                    {
                        "statement_import_id": import_id,
                        "account_id": account_id,
                        "instrument_id": instrument_id,
                        "transaction_date": row.date.isoformat(),
                        "type": row.type,
                        "quantity": str(row.quantity),
                        "price_original": str(row.price),
                        "amount_original": str(row.amount),
                        "currency": currency,
                        "amount_usd": str(amount_usd) if amount_usd is not None else None,
                        "description": row.description,
                        **common_fx,
                    }
                ).execute()
            count += 1
        except Exception as exc:
            log_import_error(client, import_id, index, row.__dict__, str(exc))
    return count


def position_metrics_supported(client: Client) -> bool:
    global _POSITION_METRICS_SUPPORTED
    if _POSITION_METRICS_SUPPORTED is not None:
        return _POSITION_METRICS_SUPPORTED
    try:
        client.table("positions_current").select(POSITION_METRIC_COLUMNS).limit(1).execute()
        _POSITION_METRICS_SUPPORTED = True
    except Exception:
        _POSITION_METRICS_SUPPORTED = False
    return _POSITION_METRICS_SUPPORTED


def _position_metric_payload(row: NormalizedRow) -> dict[str, str | None]:
    payload = {
        "cost_original": str(row.cost) if row.cost is not None else None,
        "unrealized_pnl_original": str(row.unrealized_pnl) if row.unrealized_pnl is not None else None,
        "income_original": str(row.income) if row.income is not None else None,
        "total_pnl_original": str(row.total_pnl) if row.total_pnl is not None else None,
        "pnl_pct": None,
    }
    if row.total_pnl is not None and row.cost not in (None, Decimal("0")):
        payload["pnl_pct"] = str((row.total_pnl / row.cost).quantize(Decimal("0.000001")))
    return payload


def _clear_existing_snapshot_positions(
    client: Client,
    rows: list[NormalizedRow],
    account_cache: dict[tuple[str, str], str],
) -> None:
    snapshots = [row for row in rows if row.type == "position_snapshot"]
    if not snapshots:
        return

    groups: dict[tuple[str, str, date], str] = {}
    for row in snapshots:
        account_key = (row.provider, row.account_name)
        base_currency = "USD" if row.provider.upper() == "IBKR" else ("CNY" if row.provider == "HSBC China" else row.currency.upper())
        account_id = account_cache.get(account_key)
        if account_id is None:
            account_id = upsert_account(client, row.provider, row.account_name, base_currency)
            account_cache[account_key] = account_id
        groups[(row.provider, row.account_name, row.date)] = account_id

    for (_, _, valuation_date), account_id in groups.items():
        client.table("positions_current").delete().eq("account_id", account_id).eq("valuation_date", valuation_date.isoformat()).execute()
