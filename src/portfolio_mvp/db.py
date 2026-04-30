from __future__ import annotations

from typing import Any

from supabase import Client, create_client

from portfolio_mvp.config import Settings, get_settings


class MissingSupabaseConfig(RuntimeError):
    pass


def get_supabase(use_service_role: bool = False, settings: Settings | None = None) -> Client:
    settings = settings or get_settings()
    key = settings.supabase_service_role_key if use_service_role else settings.supabase_anon_key
    if not settings.supabase_url or not key:
        key_name = "SUPABASE_SERVICE_ROLE_KEY" if use_service_role else "SUPABASE_ANON_KEY"
        raise MissingSupabaseConfig(f"Missing SUPABASE_URL or {key_name}. Copy .env.example to .env and fill it in.")
    return create_client(settings.supabase_url, key)


def table_exists(client: Client, table: str) -> bool:
    try:
        client.table(table).select("*").limit(1).execute()
        return True
    except Exception:
        return False


def fetch_dashboard_data(client: Client) -> dict[str, list[dict[str, Any]]]:
    """Fetch dashboard tables through read-only Supabase client."""
    return {
        "positions": client.table("positions_current").select(
            "*, accounts(account_name, provider, base_currency), instruments(symbol, name, isin, asset_type)"
        ).execute().data
        or [],
        "imports": client.table("statement_imports").select("*").order("created_at", desc=True).limit(20).execute().data
        or [],
        "errors": client.table("import_errors").select("*").order("created_at", desc=True).limit(20).execute().data
        or [],
        "fx_rates": client.table("fx_rates").select("*").order("rate_date", desc=True).limit(50).execute().data
        or [],
    }

