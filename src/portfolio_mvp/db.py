from __future__ import annotations

from typing import Any

import httpx
from supabase import Client, ClientOptions, create_client

from portfolio_mvp.config import Settings, get_settings


class MissingSupabaseConfig(RuntimeError):
    pass


def get_supabase(use_service_role: bool = False, settings: Settings | None = None) -> Client:
    settings = settings or get_settings()
    key = settings.supabase_service_role_key if use_service_role else settings.supabase_anon_key
    if not settings.supabase_url or not key:
        key_name = "SUPABASE_SERVICE_ROLE_KEY" if use_service_role else "SUPABASE_ANON_KEY"
        raise MissingSupabaseConfig(
            f"Missing SUPABASE_URL or {key_name}. "
            "Set them in .env for local use, or in Streamlit Secrets for cloud deployment."
        )
    return create_client(
        settings.supabase_url,
        key,
        options=ClientOptions(httpx_client=httpx.Client(timeout=120, trust_env=False)),
    )


def table_exists(client: Client, table: str) -> bool:
    try:
        client.table(table).select("*").limit(1).execute()
        return True
    except Exception:
        return False


def _select_optional(client: Client, table: str, select: str = "*", order_by: str | None = None, desc: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    try:
        query = client.table(table).select(select)
        if order_by:
            query = query.order(order_by, desc=desc)
        if limit:
            query = query.limit(limit)
        return query.execute().data or []
    except Exception:
        return []


def _select_all(
    client: Client,
    table: str,
    select: str = "*",
    *,
    order_by: tuple[tuple[str, bool], ...] = (),
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Read every row without relying on Supabase's single-response row limit."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        query = client.table(table).select(select)
        for column, desc in order_by:
            query = query.order(column, desc=desc)
        batch = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        start += page_size


def fetch_dashboard_data(client: Client) -> dict[str, list[dict[str, Any]]]:
    """Fetch dashboard tables through read-only Supabase client."""
    return {
        "positions": _select_all(
            client,
            "positions_current",
            "*, accounts(account_name, provider, base_currency), instruments(symbol, name, isin, asset_type)",
            order_by=(("valuation_date", False), ("id", False)),
        ),
        "imports": client.table("statement_imports").select("*").order("created_at", desc=True).limit(20).execute().data
        or [],
        "errors": client.table("import_errors").select("*").order("created_at", desc=True).limit(20).execute().data
        or [],
        "fx_rates": client.table("fx_rates").select("*").order("rate_date", desc=True).limit(50).execute().data
        or [],
        "fund_navs": _select_optional(client, "fund_navs", "*", "nav_date", True, 200),
    }
