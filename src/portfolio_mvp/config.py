from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False


load_dotenv()


@dataclass(frozen=True)
class Settings:
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    streamlit_password: str = os.getenv("STREAMLIT_PASSWORD", "")
    fx_api_url: str = os.getenv("FX_API_URL", "https://open.er-api.com/v6/latest/USD")
    ibkr_host: str = os.getenv("IBKR_HOST", "127.0.0.1")
    ibkr_port: int = int(os.getenv("IBKR_PORT", "7497"))
    ibkr_client_id: int = int(os.getenv("IBKR_CLIENT_ID", "11"))

    @property
    def has_supabase_read_config(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def has_supabase_write_config(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)


def get_settings() -> Settings:
    return Settings()
