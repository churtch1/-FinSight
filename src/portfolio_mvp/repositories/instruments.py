from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio_mvp.models import normalize_asset_type

if TYPE_CHECKING:
    from supabase import Client


def resolve_instrument(
    client: "Client",
    code: str,
    name: str,
    isin: str,
    currency: str,
    asset_type: str,
    provider: str = "unknown",
) -> str:
    code = (code or "").strip()
    name = (name or code or "Unknown").strip()
    isin = (isin or "").strip()
    provider_code = code or None
    alias = code or isin or name
    currency = currency.upper()

    if alias:
        alias_rows = (
            client.table("instrument_aliases")
            .select("instrument_id")
            .eq("provider", provider)
            .eq("alias", alias)
            .limit(1)
            .execute()
            .data
        )
        if alias_rows:
            return alias_rows[0]["instrument_id"]

    query = client.table("instruments").select("id")
    if isin:
        rows = query.eq("isin", isin).limit(1).execute().data
    elif code:
        rows = query.eq("symbol", code).eq("currency", currency).limit(1).execute().data
    else:
        rows = query.eq("name", name).eq("currency", currency).limit(1).execute().data

    if rows:
        instrument_id = rows[0]["id"]
    else:
        normalized_asset_type = normalize_asset_type(asset_type)
        payload = {
            "symbol": code or None,
            "name": name,
            "isin": isin or None,
            "provider_code": provider_code,
            "currency": currency,
            "asset_type": normalized_asset_type,
            "mapping_status": "confirmed" if code or isin else "needs_review",
        }
        instrument_id = client.table("instruments").insert(payload).execute().data[0]["id"]

    if alias:
        client.table("instrument_aliases").upsert(
            {
                "instrument_id": instrument_id,
                "provider": provider,
                "alias": alias,
                "alias_type": "auto",
            },
            on_conflict="provider,alias",
        ).execute()
    return instrument_id

