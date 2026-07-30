from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False


ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


def load_project_env(*, override: bool = False) -> None:
    load_dotenv(ENV_PATH, override=override)


load_project_env()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    supabase_url: str = field(default_factory=lambda: _env("SUPABASE_URL"))
    supabase_anon_key: str = field(default_factory=lambda: _env("SUPABASE_ANON_KEY"))
    supabase_service_role_key: str = field(default_factory=lambda: _env("SUPABASE_SERVICE_ROLE_KEY"))
    streamlit_password: str = field(default_factory=lambda: _env("STREAMLIT_PASSWORD"))
    fx_api_url: str = field(default_factory=lambda: _env("FX_API_URL", "https://open.er-api.com/v6/latest/USD"))
    fund_nav_api_url: str = field(
        default_factory=lambda: _env("FUND_NAV_API_URL", "https://fundgz.1234567.com.cn/js/{fund_code}.js")
    )
    dashscope_api_key: str = field(default_factory=lambda: _env("DASHSCOPE_API_KEY"))
    dashscope_ocr_model: str = field(default_factory=lambda: _env("DASHSCOPE_OCR_MODEL", "qwen3.7-plus"))
    dashscope_portfolio_model: str = field(default_factory=lambda: _env("DASHSCOPE_PORTFOLIO_MODEL", "qwen3.7-plus"))
    dashscope_compatible_api_url: str = field(
        default_factory=lambda: _env(
            "DASHSCOPE_COMPATIBLE_API_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
    )
    ibkr_flex_token: str = field(default_factory=lambda: _env("IBKR_FLEX_TOKEN"))
    ibkr_flex_query_id: str = field(default_factory=lambda: _env("IBKR_FLEX_QUERY_ID", "1587428"))

    @property
    def has_supabase_read_config(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def has_supabase_write_config(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)



def get_settings() -> Settings:
    load_project_env(override=True)
    return Settings()
