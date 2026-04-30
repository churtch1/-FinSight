from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


def upsert_account(
    client: "Client",
    provider: str,
    account_name: str,
    base_currency: str,
    account_type: str = "other",
    account_number_masked: str | None = None,
) -> str:
    payload = {
        "provider": provider,
        "account_name": account_name,
        "account_number_masked": account_number_masked,
        "account_type": account_type,
        "base_currency": base_currency.upper(),
        "status": "active",
    }
    client.table("accounts").upsert(payload, on_conflict="provider,account_name").execute()
    rows = (
        client.table("accounts")
        .select("id")
        .eq("provider", provider)
        .eq("account_name", account_name)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["id"]

