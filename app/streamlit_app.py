from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import sys
import tempfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PROJECT_ENV_PATH = ROOT / ".env"
try:
    from dotenv import load_dotenv as load_dashboard_dotenv
except ImportError:
    load_dashboard_dotenv = None

if load_dashboard_dotenv is not None:
    load_dashboard_dotenv(PROJECT_ENV_PATH, override=True)
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portfolio_mvp.config import Settings, get_settings
from portfolio_mvp.db import MissingSupabaseConfig, fetch_dashboard_data, get_supabase
from portfolio_mvp.fx import FxRate, convert_to_usd, fetch_online_usd_rates, latest_rate_from_rows
from portfolio_mvp.fund_nav import EastmoneyFundNavProvider, FundNav, latest_nav_map, normalize_fund_code
from portfolio_mvp.integrations.ibkr import sync_ibkr_data
from portfolio_mvp.market_quotes import MarketQuote, YahooMarketQuoteProvider, normalize_us_symbol
from portfolio_mvp.parsers.hsbc_cn_pdf import parse_hsbc_cn_pdf
from portfolio_mvp.parsers.manual_positions import parse_manual_position_records
from portfolio_mvp.repository import (
    complete_import,
    create_import_record,
    file_sha256,
    import_normalized_rows,
    log_import_error,
    MissingFundNavTable,
    upsert_fund_navs,
    upsert_account,
)


INSTRUMENT_NAME_ZH = {
    "AAPL": "苹果",
    "COST": "好市多",
    "GOOGL": "谷歌",
    "IBKR": "盈透证券",
    "META": "Meta",
    "MSFT": "微软",
    "NFLX": "奈飞",
    "NVDA": "英伟达",
    "QQQ": "纳斯达克100 ETF",
    "SGOV": "美国超短国债 ETF",
    "VOO": "标普500 ETF",
    "USD CASH": "美元现金",
    "CNH CASH": "离岸人民币现金",
    "CNY CASH": "人民币现金",
    "HKD CASH": "港币现金",
}

ASSET_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "wealth_product": "理财",
    "gold": "黄金",
    "cash": "现金",
    "crypto": "加密资产",
    "bond": "美债",
    "other": "其他",
}

PROVIDER_LABELS = {
    "IBKR": "盈透证券",
    "HSBC China": "汇丰",
    "CMB": "招商银行",
    "Alipay": "支付宝",
}
PROVIDER_ORDER = ["盈透证券", "汇丰", "招商银行", "支付宝"]

DISPLAY_CURRENCY_LABELS = {
    "USD": "美元",
    "CNY": "人民币",
}

ASSET_ORDER = ["wealth_product", "fund", "stock", "bond", "gold", "cash", "crypto", "other"]
CURRENCY_ALIASES = {"CNH": "CNY"}
SECTION_OPTIONS = ["总览", "结构", "持仓", "操作"]
HOLDINGS_VIEW_OPTIONS = ["卡片", "表格"]
SUMMARY_OPTIONS = ["按机构", "按币种", "按资产"]
HOLDINGS_SORT_OPTIONS = ["金额↓", "金额↑", "盈亏率↓", "盈亏率↑"]
FLASH_KEY = "dashboard_flash"
HSBC_PREVIEW_KEY = "hsbc_preview_rows"
HSBC_PREVIEW_NAME_KEY = "hsbc_preview_name"
MANUAL_POSITION_DRAFT_DIR = ROOT / "manual_import_drafts"
PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}
AUTH_COOKIE_NAME = "lxy_finsight_auth"
AUTH_QUERY_TOKEN = "auth"
AUTH_QUERY_EXPIRES = "auth_exp"
AUTH_DURATION = timedelta(days=7)

NAV_ICON_SVGS = {
    "总览": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="14" width="7" height="7" rx="1.5"></rect><rect x="3" y="14" width="7" height="7" rx="1.5"></rect></svg>',
    "结构": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9v9z"></path><path d="M12 3c4.97 0 9 4.03 9 9h-9z"></path></svg>',
    "持仓": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 6V5a2 2 0 0 1 2-2h0a2 2 0 0 1 2 2v1"></path><rect x="3" y="6" width="18" height="14" rx="2"></rect><path d="M3 12h18"></path></svg>',
    "操作": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.52a2 2 0 0 1-1 1.72l-.15.1a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.52a2 2 0 0 1 1-1.72l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    "USD": '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="12" x2="12" y1="2" y2="22"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"></path></svg>',
    "CNY": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 3 6 8 6-8"></path><path d="M12 11v10"></path><path d="M8 13h8"></path><path d="M8 17h8"></path></svg>',
}

PANEL_SPECS = [
    {
        "asset_type": "wealth_product",
        "title": "理财",
        "subtitle": "理财产品总额与明细结构",
        "accent": "#F59E0B",
        "card_class": "spot-wealth",
    },
    {
        "asset_type": "fund",
        "title": "基金",
        "subtitle": "基金产品规模与持仓结构",
        "accent": "#A855F7",
        "card_class": "spot-fund",
    },
    {
        "asset_type": "stock",
        "title": "股票",
        "subtitle": "股票与 ETF 持仓，不含“其他”分类",
        "accent": "#3B82F6",
        "card_class": "spot-stock",
    },
    {
        "asset_type": "bond",
        "title": "美债",
        "subtitle": "债券持仓总览与单券分布",
        "accent": "#22C55E",
        "card_class": "spot-bond",
    },
    {
        "asset_type": "gold",
        "title": "黄金",
        "subtitle": "黄金账户、实物金和黄金定投持仓",
        "accent": "#D97706",
        "card_class": "spot-gold",
    },
]

MANUAL_POSITION_SOURCES = {
    "招商银行": {"provider": "CMB", "source": "cmb_manual_positions", "account_name": "招商银行"},
    "招商银行黄金": {
        "provider": "CMB",
        "source": "cmb_gold_manual_positions",
        "account_name": "招商银行黄金账户",
        "default_asset_type": "gold",
        "draft_hint": (
            "黄金账户截图按一条黄金持仓校正：instrument_name=招商银行黄金账户，asset_type=gold，currency=CNY；"
            "amount 取持仓金额(元)，quantity 取持仓克数，unrealized_pnl 取持有收益，"
            "total_pnl 可记录累计收益；今日收益不要写入盈亏。"
        ),
    },
    "支付宝": {"provider": "Alipay", "source": "alipay_manual_positions", "account_name": "支付宝"},
}


st.set_page_config(page_title="LXY的Finsight", layout="wide", initial_sidebar_state="collapsed")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top left, rgba(59,130,246,0.08), transparent 28%),
                radial-gradient(circle at top right, rgba(34,197,94,0.06), transparent 24%);
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        [data-testid="stMainBlockContainer"] {
            padding-top: 1.1rem;
            padding-bottom: 3rem;
            max-width: 1140px;
        }
        [data-testid="stSidebar"] {
            border-right: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent 90%);
        }
        [data-testid="stSidebar"] > div:first-child {
            background:
                linear-gradient(
                    180deg,
                    color-mix(in srgb, var(--st-secondary-background-color) 94%, var(--st-background-color) 6%) 0%,
                    color-mix(in srgb, var(--st-secondary-background-color) 86%, var(--st-background-color) 14%) 100%
                );
            padding-top: 1.25rem;
            box-shadow: 18px 0 42px rgba(15, 23, 42, 0.08);
        }
        [data-testid="stSidebar"] .sidebar-brand {
            font-size: 1.28rem;
            font-weight: 950;
            line-height: 1.08;
            margin-bottom: 0.2rem;
        }
        [data-testid="stSidebar"] .sidebar-subtitle {
            color: color-mix(in srgb, var(--st-text-color) 62%, transparent 38%);
            font-size: 0.88rem;
            line-height: 1.35;
        }
        [data-testid="stSidebar"] .sidebar-block {
            margin-bottom: 1rem;
        }
        [data-testid="stSidebar"] .sidebar-kicker {
            font-size: 0.82rem;
            font-weight: 800;
            color: var(--st-link-color);
            margin-bottom: 0.2rem;
        }
        [data-testid="stSidebar"] .sidebar-fx {
            border-radius: 18px;
            padding: 0.9rem 0.95rem;
            background: linear-gradient(180deg, rgba(37,99,235,0.12), rgba(37,99,235,0.05));
            border: 1px solid rgba(37,99,235,0.18);
            margin-bottom: 0.9rem;
        }
        [data-testid="stSidebar"] .sidebar-fx-label {
            font-size: 0.82rem;
            font-weight: 800;
            opacity: 0.82;
            margin-bottom: 0.18rem;
        }
        [data-testid="stSidebar"] .sidebar-fx-value {
            font-size: 1.16rem;
            font-weight: 900;
            line-height: 1.15;
        }
        [data-testid="stSidebar"] .sidebar-fx-meta {
            font-size: 0.8rem;
            opacity: 0.7;
            margin-top: 0.2rem;
        }
        [data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p {
            font-size: 1rem !important;
            font-weight: 800 !important;
        }
        .sidebar-nav {
            margin: 1rem 0 1.1rem 0;
        }
        .sidebar-nav-title {
            color: color-mix(in srgb, var(--st-text-color) 60%, transparent 40%);
            font-size: 0.95rem;
            font-weight: 900;
            letter-spacing: 0;
            margin: 0 0 0.52rem 0.1rem;
        }
        .sidebar-nav-list {
            display: grid;
            grid-template-columns: 1fr;
            gap: 0.16rem;
            width: 100%;
        }
        .sidebar-nav-item {
            position: relative;
            display: grid;
            grid-template-columns: 1.35rem 1fr;
            align-items: center;
            gap: 0.64rem;
            min-height: 2.85rem;
            width: 100%;
            box-sizing: border-box;
            padding: 0 0.78rem 0 0.95rem;
            border-radius: 10px;
            color: #6B7280;
            text-decoration: none !important;
            font-size: 1rem;
            font-weight: 760;
            line-height: 1;
            background: transparent;
            transition: background 120ms ease, color 120ms ease;
        }
        .sidebar-nav-item:hover {
            background: rgba(17, 24, 39, 0.035);
            color: color-mix(in srgb, var(--st-text-color) 78%, #6B7280 22%);
            text-decoration: none !important;
        }
        .sidebar-nav-item svg {
            width: 1.08rem;
            height: 1.08rem;
            stroke: currentColor;
            stroke-width: 2;
            stroke-linecap: round;
            stroke-linejoin: round;
            fill: none;
        }
        .sidebar-nav-item.active {
            background: #EBF5FF;
            color: #1A73E8;
            font-weight: 860;
        }
        .sidebar-nav-item.active::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0.55rem;
            bottom: 0.55rem;
            width: 4px;
            border-radius: 0 999px 999px 0;
            background: #1A73E8;
        }
        .sidebar-nav-label {
            display: block;
        }
        .filter-nav {
            margin: 0.72rem 0 0.95rem 0;
        }
        .filter-nav-title {
            color: var(--st-text-color);
            font-size: 1rem;
            font-weight: 900;
            letter-spacing: 0;
            margin-bottom: 0.46rem;
        }
        .filter-nav-list {
            display: grid;
            grid-template-columns: repeat(var(--filter-count, 4), minmax(0, 1fr));
            width: 100%;
            border: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent 88%);
            border-radius: 10px;
            overflow: hidden;
            background: color-mix(in srgb, var(--st-background-color) 84%, var(--st-secondary-background-color) 16%);
        }
        .filter-nav-item {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 2.58rem;
            padding: 0 0.62rem;
            border-right: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent 90%);
            color: #6B7280;
            text-decoration: none !important;
            font-size: 0.96rem;
            font-weight: 720;
            line-height: 1;
            background: transparent;
            transition: background 120ms ease, color 120ms ease;
        }
        .filter-nav-item:last-child {
            border-right: 0;
        }
        .filter-nav-item:hover {
            background: rgba(17, 24, 39, 0.035);
            color: color-mix(in srgb, var(--st-text-color) 78%, #6B7280 22%);
            text-decoration: none !important;
        }
        .filter-nav-item.active {
            background: #EBF5FF;
            color: #1A73E8;
            font-weight: 860;
            box-shadow: inset 4px 0 0 #1A73E8;
        }
        div[data-testid="stMetric"] {
            background: linear-gradient(
                180deg,
                color-mix(in srgb, var(--st-secondary-background-color) 90%, var(--st-background-color) 10%) 0%,
                color-mix(in srgb, var(--st-secondary-background-color) 84%, var(--st-background-color) 16%) 100%
            );
            border: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent 90%);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
        }
        .hero-card,
        .soft-card,
        .ops-card,
        .holding-card {
            background: linear-gradient(
                180deg,
                color-mix(in srgb, var(--st-secondary-background-color) 90%, var(--st-background-color) 10%) 0%,
                color-mix(in srgb, var(--st-secondary-background-color) 84%, var(--st-background-color) 16%) 100%
            );
            border: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent 90%);
            border-radius: 18px;
            padding: 1rem 1rem 0.95rem 1rem;
            box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
        }
        .hero-card {
            padding: 0.9rem 0.95rem 0.85rem 0.95rem;
            margin-bottom: 0.2rem;
        }
        .hero-fx-card {
            margin-top: 0.68rem;
            border-radius: 14px;
            padding: 0.62rem 0.72rem;
            border: 1px solid color-mix(in srgb, var(--st-link-color) 20%, transparent 80%);
            background: linear-gradient(
                180deg,
                color-mix(in srgb, var(--st-link-color) 10%, var(--st-secondary-background-color) 90%) 0%,
                color-mix(in srgb, var(--st-link-color) 4%, var(--st-background-color) 96%) 100%
            );
        }
        .hero-fx-label {
            font-size: 0.78rem;
            font-weight: 800;
            color: color-mix(in srgb, var(--st-text-color) 72%, transparent 28%);
            margin-bottom: 0.18rem;
        }
        .hero-fx-value {
            font-size: 1.08rem;
            font-weight: 900;
            color: var(--st-text-color);
            line-height: 1.15;
        }
        .hero-fx-meta {
            font-size: 0.78rem;
            color: color-mix(in srgb, var(--st-text-color) 62%, transparent 38%);
            margin-top: 0.2rem;
        }
        .hero-kicker {
            font-size: 0.78rem;
            color: var(--st-link-color);
            letter-spacing: 0.02em;
            font-weight: 700;
            margin-bottom: 0.24rem;
        }
        .hero-title {
            font-size: 1.76rem;
            font-weight: 950;
            color: var(--st-text-color);
            line-height: 1.08;
            margin-bottom: 0.24rem;
            letter-spacing: 0;
            text-rendering: geometricPrecision;
        }
        .hero-subtitle,
        .muted-copy {
            color: color-mix(in srgb, var(--st-text-color) 72%, transparent 28%);
            font-size: 0.96rem;
            line-height: 1.38;
        }
        .badge-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.32rem;
            margin-top: 0.52rem;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.22rem 0.54rem;
            border-radius: 999px;
            background: color-mix(in srgb, var(--st-link-color) 10%, var(--st-secondary-background-color) 90%);
            color: var(--st-text-color);
            font-size: 0.78rem;
            font-weight: 700;
        }
        .section-title {
            font-size: 1.22rem;
            font-weight: 860;
            color: var(--st-text-color);
            margin-bottom: 0.2rem;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] {
            gap: 0;
            width: 100%;
            border: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent 88%);
            border-radius: 10px;
            overflow: hidden;
            background: color-mix(in srgb, var(--st-background-color) 84%, var(--st-secondary-background-color) 16%);
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button {
            position: relative;
            min-height: 2.58rem;
            border-radius: 0 !important;
            border: 0 !important;
            border-right: 1px solid color-mix(in srgb, var(--st-text-color) 10%, transparent 90%) !important;
            background: transparent !important;
            font-weight: 720 !important;
            font-size: 0.96rem !important;
            color: #6B7280 !important;
            box-shadow: none !important;
            transition: background 120ms ease, color 120ms ease;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button:last-child {
            border-right: 0 !important;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button:hover {
            background: rgba(17, 24, 39, 0.035) !important;
            color: color-mix(in srgb, var(--st-text-color) 78%, #6B7280 22%) !important;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-pressed="true"],
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-checked="true"],
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-selected="true"],
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[data-selected="true"],
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[kind="primary"],
        div[data-testid="stSegmentedControl"] button[data-testid*="segmented_controlActive"],
        div[data-testid="stSegmentedControl"] button[data-testid*="Active"],
        button[data-testid*="segmented_controlActive"],
        button[data-testid*="Active"][data-testid*="segmented_control"] {
            background: #EBF5FF !important;
            color: #1A73E8 !important;
            font-weight: 860 !important;
            border-color: transparent !important;
            box-shadow: inset 4px 0 0 #1A73E8 !important;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-pressed="true"] *,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-selected="true"] *,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[data-selected="true"] *,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[kind="primary"] *,
        div[data-testid="stSegmentedControl"] button[data-testid*="segmented_controlActive"] *,
        div[data-testid="stSegmentedControl"] button[data-testid*="Active"] *,
        button[data-testid*="segmented_controlActive"] *,
        button[data-testid*="Active"][data-testid*="segmented_control"] * {
            color: #1A73E8 !important;
            border-color: transparent !important;
        }
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-pressed="true"]::before,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-checked="true"]::before,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-selected="true"]::before,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[data-selected="true"]::before,
        div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[kind="primary"]::before {
            border-color: transparent !important;
            background: transparent !important;
        }
        .ui-anchor {
            height: 0;
        }
        .section-subtitle {
            color: color-mix(in srgb, var(--st-text-color) 68%, transparent 32%);
            font-size: 0.96rem;
            margin-bottom: 0.8rem;
        }
        .spotlight-title {
            font-size: 1.18rem;
            font-weight: 860;
            color: var(--st-text-color);
            margin-bottom: 0.1rem;
        }
        .spotlight-subtitle {
            color: color-mix(in srgb, var(--st-text-color) 72%, transparent 28%);
            font-size: 0.9rem;
            margin-bottom: 0.65rem;
        }
        .spotlight-chip {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            background: color-mix(in srgb, var(--spot-accent) 18%, var(--st-secondary-background-color) 82%);
            color: color-mix(in srgb, var(--st-text-color) 82%, transparent 18%);
            font-size: 0.76rem;
            font-weight: 600;
            margin-right: 0.38rem;
            margin-bottom: 0.35rem;
        }
        .spotlight-shell {
            border-radius: 22px;
            padding: 1rem 1rem 0.7rem 1rem;
            margin-bottom: 0;
            border: 1px solid color-mix(in srgb, var(--spot-accent) 22%, transparent 78%);
            border-bottom: 0;
            border-radius: 22px 22px 0 0;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
        }
        .spotlight-shell.spot-stock,
        div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-stock) + div[data-testid="stElementContainer"] {
            background:
                linear-gradient(
                    180deg,
                    color-mix(in srgb, #3B82F6 18%, var(--st-secondary-background-color) 82%) 0%,
                    color-mix(in srgb, #3B82F6 9%, var(--st-background-color) 91%) 100%
                );
            border-color: color-mix(in srgb, #3B82F6 24%, transparent 76%);
        }
        .spotlight-shell.spot-bond,
        div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-bond) + div[data-testid="stElementContainer"] {
            background:
                linear-gradient(
                    180deg,
                    color-mix(in srgb, #22C55E 18%, var(--st-secondary-background-color) 82%) 0%,
                    color-mix(in srgb, #22C55E 9%, var(--st-background-color) 91%) 100%
                );
            border-color: color-mix(in srgb, #22C55E 24%, transparent 76%);
        }
        .spotlight-shell.spot-fund,
        div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-fund) + div[data-testid="stElementContainer"] {
            background:
                linear-gradient(
                    180deg,
                    color-mix(in srgb, #A855F7 18%, var(--st-secondary-background-color) 82%) 0%,
                    color-mix(in srgb, #A855F7 9%, var(--st-background-color) 91%) 100%
                );
            border-color: color-mix(in srgb, #A855F7 24%, transparent 76%);
        }
        .spotlight-shell.spot-wealth,
        div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-wealth) + div[data-testid="stElementContainer"] {
            background:
                linear-gradient(
                    180deg,
                    color-mix(in srgb, #F59E0B 18%, var(--st-secondary-background-color) 82%) 0%,
                    color-mix(in srgb, #F59E0B 9%, var(--st-background-color) 91%) 100%
                );
            border-color: color-mix(in srgb, #F59E0B 24%, transparent 76%);
        }
        div[data-testid="stElementContainer"]:has(.spotlight-shell) + div[data-testid="stElementContainer"] {
            margin-top: 0;
            margin-bottom: 1rem;
            padding: 0 0.9rem 0.85rem 0.9rem;
            border-style: solid;
            border-width: 0 1px 1px 1px;
            border-radius: 0 0 22px 22px;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
        }
        div[data-testid="stElementContainer"]:has(.spotlight-shell) + div[data-testid="stElementContainer"] [data-testid="stPlotlyChart"] {
            background: transparent;
        }
        .spotlight-metrics {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.72rem;
            margin-top: 0.85rem;
            margin-bottom: 0.65rem;
        }
        .spotlight-metric {
            background: color-mix(in srgb, var(--st-background-color) 70%, white 30%);
            border: 1px solid color-mix(in srgb, var(--spot-accent) 18%, transparent 82%);
            border-radius: 16px;
            padding: 0.75rem 0.78rem;
            backdrop-filter: blur(10px);
        }
        .spotlight-metric-label {
            color: color-mix(in srgb, var(--st-text-color) 66%, transparent 34%);
            font-size: 0.84rem;
            margin-bottom: 0.16rem;
        }
        .spotlight-metric-value {
            color: var(--st-text-color);
            font-size: 1.16rem;
            font-weight: 860;
            line-height: 1.15;
        }
        .ops-card {
            height: 100%;
        }
        .ops-topline {
            width: 100%;
            height: 6px;
            border-radius: 999px;
            margin-bottom: 0.9rem;
        }
        .ops-local {
            background: linear-gradient(90deg, #2563eb, #60a5fa);
        }
        .ops-cloud {
            background: linear-gradient(90deg, #0f766e, #2dd4bf);
        }
        .ops-title {
            font-size: 1.08rem;
            font-weight: 820;
            color: var(--st-text-color);
            margin-bottom: 0.16rem;
        }
        .ops-tag {
            display: inline-block;
            padding: 0.2rem 0.58rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            margin-bottom: 0.55rem;
        }
        .ops-tag-local {
            background: rgba(37, 99, 235, 0.14);
            color: #1d4ed8;
        }
        .ops-tag-cloud {
            background: rgba(13, 148, 136, 0.14);
            color: #0f766e;
        }
        .holding-card {
            margin-bottom: 0.8rem;
        }
        .holding-header {
            display: flex;
            justify-content: space-between;
            gap: 0.8rem;
            align-items: flex-start;
        }
        .holding-name {
            font-size: 1.28rem;
            font-weight: 860;
            color: var(--st-text-color);
            line-height: 1.18;
            margin-bottom: 0.18rem;
        }
        .holding-code {
            color: color-mix(in srgb, var(--st-text-color) 65%, transparent 35%);
            font-size: 0.88rem;
        }
        .holding-value {
            text-align: right;
        }
        .holding-value-main {
            font-size: 1.16rem;
            font-weight: 840;
            color: var(--st-text-color);
            line-height: 1.15;
        }
        .holding-value-sub {
            font-size: 0.88rem;
            color: color-mix(in srgb, var(--st-text-color) 65%, transparent 35%);
            margin-top: 0.12rem;
        }
        .holding-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.65rem 0.9rem;
            margin-top: 0.9rem;
        }
        .mini-label {
            font-size: 0.84rem;
            color: color-mix(in srgb, var(--st-text-color) 62%, transparent 38%);
            margin-bottom: 0.12rem;
        }
        .mini-value {
            font-size: 1rem;
            font-weight: 760;
            color: var(--st-text-color);
        }
        .pnl-rate {
            font-size: 1.18rem;
            font-weight: 860;
            letter-spacing: 0;
        }
        .pnl-up {
            color: #15803d;
        }
        .pnl-down {
            color: #b91c1c;
        }
        .tiny-note {
            color: color-mix(in srgb, var(--st-text-color) 62%, transparent 38%);
            font-size: 0.86rem;
            margin-top: 0.35rem;
        }
        [data-testid="stMetricLabel"] p {
            font-size: 0.98rem !important;
            font-weight: 800 !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.55rem !important;
            font-weight: 900 !important;
        }
        div[data-testid="stCaptionContainer"] {
            font-size: 0.92rem !important;
        }
        label[data-testid="stWidgetLabel"] p {
            font-size: 1rem !important;
            font-weight: 800 !important;
        }
        div[data-baseweb="input"] {
            min-height: 2.58rem;
            border-radius: 10px !important;
            border: 1px solid color-mix(in srgb, var(--st-text-color) 12%, transparent 88%) !important;
            background: color-mix(in srgb, var(--st-background-color) 84%, var(--st-secondary-background-color) 16%) !important;
            box-shadow: none !important;
        }
        div[data-baseweb="input"]:focus-within {
            border-color: color-mix(in srgb, #1A73E8 35%, transparent 65%) !important;
            box-shadow: inset 4px 0 0 #1A73E8 !important;
        }
        .stTextInput input {
            font-size: 1rem !important;
            color: var(--st-text-color) !important;
        }
        @media (prefers-color-scheme: dark) {
            .hero-card,
            .soft-card,
            .ops-card,
            .holding-card,
            div[data-testid="stMetric"] {
                background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.025));
                box-shadow: 0 10px 24px rgba(0, 0, 0, 0.24);
                border-color: rgba(255,255,255,0.08);
            }
            div[data-testid="stElementContainer"]:has(.nav-anchor) + div[data-testid="stElementContainer"] [data-baseweb="button-group"] > button {
                background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.03)) !important;
                border-color: rgba(255,255,255,0.09) !important;
                color: rgba(255,255,255,0.88) !important;
            }
            div[data-testid="stElementContainer"]:has(.nav-anchor) + div[data-testid="stElementContainer"] [data-baseweb="button-group"] > button[aria-pressed="true"],
            div[data-testid="stElementContainer"]:has(.currency-anchor) + div[data-testid="stElementContainer"] [data-baseweb="button-group"] > button[aria-pressed="true"] {
                color: white !important;
            }
            .spotlight-shell {
                box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28);
                border-color: color-mix(in srgb, var(--spot-accent) 30%, rgba(255,255,255,0.14) 70%);
            }
            .spotlight-title {
                color: white;
            }
            .spotlight-subtitle {
                color: rgba(255,255,255,0.82);
            }
            .spotlight-chip {
                background: color-mix(in srgb, var(--spot-accent) 28%, rgba(255,255,255,0.06) 72%);
                color: white;
            }
            .spotlight-metric {
                background: color-mix(in srgb, var(--st-secondary-background-color) 74%, rgba(255,255,255,0.03) 26%);
                border-color: rgba(255,255,255,0.08);
            }
            .spotlight-metric-label {
                color: rgba(255,255,255,0.78);
            }
            .spotlight-metric-value {
                color: white;
            }
            .spotlight-shell.spot-stock,
            div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-stock) + div[data-testid="stElementContainer"] {
                background:
                    linear-gradient(
                        180deg,
                        color-mix(in srgb, #3B82F6 30%, rgba(15,23,42,0.96) 70%) 0%,
                        color-mix(in srgb, #3B82F6 18%, rgba(2,6,23,0.98) 82%) 100%
                    );
            }
            .spotlight-shell.spot-bond,
            div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-bond) + div[data-testid="stElementContainer"] {
                background:
                    linear-gradient(
                        180deg,
                        color-mix(in srgb, #22C55E 30%, rgba(15,23,42,0.96) 70%) 0%,
                        color-mix(in srgb, #22C55E 18%, rgba(2,6,23,0.98) 82%) 100%
                    );
            }
            .spotlight-shell.spot-fund,
            div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-fund) + div[data-testid="stElementContainer"] {
                background:
                    linear-gradient(
                        180deg,
                        color-mix(in srgb, #A855F7 30%, rgba(15,23,42,0.96) 70%) 0%,
                        color-mix(in srgb, #A855F7 18%, rgba(2,6,23,0.98) 82%) 100%
                    );
            }
            .spotlight-shell.spot-wealth,
            div[data-testid="stElementContainer"]:has(.spotlight-shell.spot-wealth) + div[data-testid="stElementContainer"] {
                background:
                    linear-gradient(
                        180deg,
                        color-mix(in srgb, #F59E0B 34%, rgba(15,23,42,0.96) 66%) 0%,
                        color-mix(in srgb, #F59E0B 20%, rgba(2,6,23,0.98) 80%) 100%
                    );
            }
            div[data-testid="stElementContainer"]:has(.spotlight-shell) + div[data-testid="stElementContainer"] {
                box-shadow: 0 16px 34px rgba(0, 0, 0, 0.28);
                border-color: rgba(255,255,255,0.08);
            }
            .ops-tag-local {
                color: #93c5fd;
            }
            .ops-tag-cloud {
                color: #99f6e4;
            }
            .pnl-up {
                color: #86efac;
            }
            .pnl-down {
                color: #fca5a5;
            }
            .hero-fx-card,
            [data-testid="stSidebar"] .sidebar-fx {
                border-color: rgba(96, 165, 250, 0.26);
                background: linear-gradient(180deg, rgba(59,130,246,0.18), rgba(30,41,59,0.42));
            }
            .sidebar-nav-item {
                color: rgba(229, 231, 235, 0.68);
            }
            .sidebar-nav-item:hover {
                background: rgba(255,255,255,0.055);
                color: rgba(255,255,255,0.88);
            }
            .sidebar-nav-item.active {
                background: rgba(26, 115, 232, 0.18);
                color: #93C5FD;
            }
            .sidebar-nav-item.active::before {
                background: #60A5FA;
            }
            .filter-nav-list {
                border-color: rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.025);
            }
            .filter-nav-item {
                border-right-color: rgba(255,255,255,0.08);
                color: rgba(229, 231, 235, 0.68);
            }
            .filter-nav-item:hover {
                background: rgba(255,255,255,0.055);
                color: rgba(255,255,255,0.88);
            }
            .filter-nav-item.active {
                background: rgba(26, 115, 232, 0.18);
                color: #93C5FD;
                box-shadow: inset 4px 0 0 #60A5FA;
            }
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] {
                border-color: rgba(255,255,255,0.10);
                background: rgba(255,255,255,0.025);
            }
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button {
                border-right-color: rgba(255,255,255,0.08) !important;
                color: rgba(229, 231, 235, 0.68) !important;
            }
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button:hover {
                background: rgba(255,255,255,0.055) !important;
                color: rgba(255,255,255,0.88) !important;
            }
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-pressed="true"],
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-checked="true"],
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-selected="true"],
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[data-selected="true"],
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[kind="primary"],
            div[data-testid="stSegmentedControl"] button[data-testid*="segmented_controlActive"],
            div[data-testid="stSegmentedControl"] button[data-testid*="Active"],
            button[data-testid*="segmented_controlActive"],
            button[data-testid*="Active"][data-testid*="segmented_control"] {
                background: rgba(26, 115, 232, 0.18) !important;
                color: #93C5FD !important;
                border-color: transparent !important;
                box-shadow: inset 4px 0 0 #60A5FA !important;
            }
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-pressed="true"] *,
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-checked="true"] *,
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[aria-selected="true"] *,
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[data-selected="true"] *,
            div[data-testid="stSegmentedControl"] [data-baseweb="button-group"] > button[kind="primary"] *,
            div[data-testid="stSegmentedControl"] button[data-testid*="segmented_controlActive"] *,
            div[data-testid="stSegmentedControl"] button[data-testid*="Active"] *,
            button[data-testid*="segmented_controlActive"] *,
            button[data-testid*="Active"][data-testid*="segmented_control"] * {
                color: #93C5FD !important;
                border-color: transparent !important;
            }
            div[data-baseweb="input"] {
                border-color: rgba(255,255,255,0.10) !important;
                background: rgba(255,255,255,0.025) !important;
            }
            div[data-baseweb="input"]:focus-within {
                border-color: rgba(96, 165, 250, 0.42) !important;
                box-shadow: inset 4px 0 0 #60A5FA !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def auth_cookie_value(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"lxy-finsight-auth-v1", hashlib.sha256).hexdigest()


def auth_query_signature(password: str, expires_at: int) -> str:
    payload = f"lxy-finsight-auth-v1:{expires_at}".encode("utf-8")
    return hmac.new(password.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def auth_query_payload(settings: Settings) -> tuple[str, str]:
    expires_at = int((datetime.now(timezone.utc) + AUTH_DURATION).timestamp())
    signature = auth_query_signature(settings.streamlit_password, expires_at)
    return signature, str(expires_at)


def has_valid_auth_query(settings: Settings) -> bool:
    if not settings.streamlit_password:
        return True
    signature = query_param_value(AUTH_QUERY_TOKEN)
    expires_raw = query_param_value(AUTH_QUERY_EXPIRES)
    if not signature or not expires_raw:
        return False
    try:
        expires_at = int(expires_raw)
    except (TypeError, ValueError):
        return False
    if expires_at < int(datetime.now(timezone.utc).timestamp()):
        return False
    expected = auth_query_signature(settings.streamlit_password, expires_at)
    return hmac.compare_digest(signature, expected)


def has_valid_auth_cookie(settings: Settings) -> bool:
    if not settings.streamlit_password:
        return True
    try:
        cookie_value = st.context.cookies.get(AUTH_COOKIE_NAME, "")
    except Exception:
        return False
    return hmac.compare_digest(str(cookie_value), auth_cookie_value(settings.streamlit_password))


def set_auth_cookie(settings: Settings) -> None:
    token = auth_cookie_value(settings.streamlit_password)
    cookie_name = json.dumps(AUTH_COOKIE_NAME)
    cookie_value = json.dumps(token)
    components.html(
        f"""
        <script>
        const secure = window.location.protocol === "https:" ? "; Secure" : "";
        document.cookie = {cookie_name} + "=" + {cookie_value} + "; Max-Age=604800; Path=/; SameSite=Lax" + secure;
        </script>
        """,
        height=0,
        width=0,
    )


def ensure_auth_query(settings: Settings) -> bool:
    if has_valid_auth_query(settings):
        return False
    signature, expires_at = auth_query_payload(settings)
    st.query_params[AUTH_QUERY_TOKEN] = signature
    st.query_params[AUTH_QUERY_EXPIRES] = expires_at
    return True


def require_password() -> bool:
    settings = get_settings()
    if not settings.streamlit_password:
        return True
    if st.session_state.get("authenticated") or has_valid_auth_cookie(settings):
        st.session_state["authenticated"] = True
        return True
    with st.form("login"):
        st.subheader("LXY的Finsight")
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("进入", type="primary", icon=":material/lock_open:")
    if submitted and password == settings.streamlit_password:
        st.session_state["authenticated"] = True
        set_auth_cookie(settings)
        return True
    elif submitted:
        st.error("密码不正确。")
    return False


def require_password() -> bool:
    settings = get_settings()
    if not settings.streamlit_password:
        return True

    authenticated = (
        st.session_state.get("authenticated")
        or has_valid_auth_cookie(settings)
        or has_valid_auth_query(settings)
    )
    if authenticated:
        st.session_state["authenticated"] = True
        query_changed = ensure_auth_query(settings)
        if not has_valid_auth_cookie(settings):
            set_auth_cookie(settings)
        if query_changed:
            st.rerun()
        return True

    with st.form("login"):
        st.subheader("LXY鐨凢insight")
        password = st.text_input("璁块棶瀵嗙爜", type="password")
        submitted = st.form_submit_button("杩涘叆", type="primary", icon=":material/lock_open:")

    if submitted and password == settings.streamlit_password:
        st.session_state["authenticated"] = True
        ensure_auth_query(settings)
        set_auth_cookie(settings)
        st.rerun()
    elif submitted:
        st.error("瀵嗙爜涓嶆纭€?")
    return False


def push_flash(level: str, message: str) -> None:
    st.session_state[FLASH_KEY] = {"level": level, "message": message}


def render_flash() -> None:
    flash = st.session_state.pop(FLASH_KEY, None)
    if not flash:
        return
    level = str(flash.get("level") or "info")
    message = str(flash.get("message") or "")
    renderer = getattr(st, level, st.info)
    renderer(message)


@st.cache_data(ttl=60)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    settings = get_settings()
    if settings.has_supabase_read_config:
        client = get_supabase(use_service_role=False, settings=settings)
        data = fetch_dashboard_data(client)
        return (
            normalize_positions(pd.DataFrame(data["positions"])),
            pd.DataFrame(data["imports"]),
            pd.DataFrame(data["errors"]),
            pd.DataFrame(data["fx_rates"]),
            pd.DataFrame(data.get("fund_navs", [])),
            True,
        )
    return load_sample_data()


def normalize_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return empty_positions()

    df = df.copy()
    if "accounts" in df.columns:
        accounts = df["accounts"].apply(lambda value: value if isinstance(value, dict) else {})
        df["provider"] = accounts.apply(lambda item: item.get("provider", ""))
        df["account_name"] = accounts.apply(lambda item: item.get("account_name", ""))
        df["base_currency"] = accounts.apply(lambda item: item.get("base_currency", ""))

    if "instruments" in df.columns:
        instruments = df["instruments"].apply(lambda value: value if isinstance(value, dict) else {})
        df["symbol"] = instruments.apply(lambda item: item.get("symbol", ""))
        df["instrument_name"] = instruments.apply(lambda item: item.get("name", ""))
        df["isin"] = instruments.apply(lambda item: item.get("isin", ""))
        df["asset_type"] = instruments.apply(lambda item: item.get("asset_type", "other"))

    df = coerce_position_columns(df)
    df["currency"] = df["currency"].apply(canonical_currency)
    df = df[df["currency"] != "BASE"].copy()
    df["asset_type"] = df.apply(
        lambda row: derive_asset_type(row["asset_type"], row["symbol"], row["instrument_name"]),
        axis=1,
    )
    df["provider_label"] = df["provider"].apply(provider_label)
    df["asset_label"] = df["asset_type"].map(ASSET_LABELS).fillna("其他")
    df["display_name"] = df.apply(
        lambda row: localized_instrument_name(row["symbol"], row["instrument_name"]),
        axis=1,
    )
    return latest_account_snapshots(df)


def coerce_position_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    numeric_columns = [
        "quantity",
        "price_original",
        "market_value_original",
        "market_value_usd",
        "cost_original",
        "unrealized_pnl_original",
        "income_original",
        "total_pnl_original",
        "pnl_pct",
    ]
    for column in numeric_columns:
        if column not in df.columns:
            df[column] = pd.NA
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if "valuation_date" in df.columns:
        df["valuation_date"] = pd.to_datetime(df["valuation_date"], errors="coerce").dt.date
    else:
        df["valuation_date"] = pd.NaT

    for column in (
        "provider",
        "account_name",
        "base_currency",
        "symbol",
        "instrument_name",
        "asset_type",
        "currency",
        "quantity_source",
        "estimate_note",
        "fund_nav_date",
        "fund_nav_source",
        "fund_nav_status",
    ):
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str)
    df["quantity_source"] = df["quantity_source"].replace("", "reported")
    return df


def empty_positions() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "provider",
            "account_name",
            "base_currency",
            "symbol",
            "instrument_name",
            "display_name",
            "asset_type",
            "asset_label",
            "quantity",
            "price_original",
            "market_value_original",
            "currency",
            "market_value_usd",
            "valuation_date",
            "cost_original",
            "unrealized_pnl_original",
            "income_original",
            "total_pnl_original",
            "pnl_pct",
            "quantity_source",
            "estimate_note",
            "fund_nav_date",
            "fund_nav_source",
            "fund_nav_status",
        ]
    )


def load_sample_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    sample_path = ROOT / "sample_data" / "positions_demo.csv"
    df = normalize_positions(pd.read_csv(sample_path)) if sample_path.exists() else empty_positions()
    imports = pd.DataFrame(
        [{"source": "demo", "source_type": "csv", "status": "demo_sample", "rows_imported": len(df)}]
    )
    errors = pd.DataFrame()
    fx_rates = pd.DataFrame(
        [
            {"base_currency": "CNY", "quote_currency": "USD", "rate": 0.138, "rate_date": str(date.today()), "source": "sample"},
            {"base_currency": "HKD", "quote_currency": "USD", "rate": 0.128, "rate_date": str(date.today()), "source": "sample"},
        ]
    )
    fund_navs = pd.DataFrame(
        [
            {
                "fund_code": "270023",
                "fund_name": "Demo QDII Fund",
                "unit_nav": 2.3456,
                "accumulated_nav": 2.3456,
                "nav_date": str(date.today()),
                "source": "sample",
                "status": "ok",
            }
        ]
    )
    return df, imports, errors, fx_rates, fund_navs, False


def canonical_currency(value: str) -> str:
    currency = (value or "").strip().upper()
    return CURRENCY_ALIASES.get(currency, currency)


def provider_label(value: str) -> str:
    text = str(value or "").strip()
    return PROVIDER_LABELS.get(text, text or "未分类")


def provider_filter_options(df: pd.DataFrame) -> list[str]:
    labels = set(df.get("provider_label", pd.Series(dtype=str)).dropna().astype(str))
    ordered = [label for label in PROVIDER_ORDER if label in labels]
    remaining = sorted(label for label in labels if label and label not in PROVIDER_ORDER)
    return ["全部"] + ordered + remaining


def derive_asset_type(asset_type: str, symbol: str, instrument_name: str) -> str:
    normalized = (asset_type or "").strip().lower()
    if normalized and normalized != "other":
        return normalized
    text = f"{symbol} {instrument_name}".upper()
    if any(token in text for token in ("US-T", "UST", "TREASURY", "T-BILL", "T BILL", "BOND")):
        return "bond"
    return "other"


def localized_instrument_name(symbol: str, instrument_name: str) -> str:
    code = (symbol or "").strip().upper()
    name = (instrument_name or "").strip()
    if code.startswith("IBCID") and "US-T" in name:
        return name.replace("US-T", "美国国债", 1)
    if code == "US-T":
        return "美国国债"
    return INSTRUMENT_NAME_ZH.get(code, name or code)


def latest_account_snapshots(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    latest_dates = df.groupby(["provider", "account_name"], dropna=False)["valuation_date"].transform("max")
    return df[df["valuation_date"] == latest_dates].copy()


def build_rate_map(fx_rates: pd.DataFrame) -> dict[str, FxRate]:
    rows = fx_rates.to_dict("records") if not fx_rates.empty else []
    currencies = {canonical_currency(str(row.get("base_currency") or "")) for row in rows}
    currencies.update({"USD", "CNY", "HKD"})
    rate_map: dict[str, FxRate] = {}

    for currency in currencies:
        if not currency:
            continue
        if currency == "USD":
            rate_map["USD"] = FxRate("USD", "USD", Decimal("1"), date.today(), "identity")
            continue
        if currency == "CNH":
            continue
        rate = latest_rate_from_rows(currency, rows)
        if rate is not None:
            rate_map[currency] = rate

    if "CNY" in rate_map:
        rate_map["CNH"] = rate_map["CNY"]
    return rate_map


def apply_fx_fallback(df: pd.DataFrame, fx_rates: pd.DataFrame) -> tuple[pd.DataFrame, str, dict[str, FxRate]]:
    df = df.copy()
    rate_map = build_rate_map(fx_rates)
    missing = df["market_value_usd"].isna() | (df["market_value_usd"] == 0)
    currencies = sorted(set(df.loc[missing, "currency"].dropna().astype(str).str.upper()) - {"USD", "", "BASE"})
    source_note = "使用已入库汇率"

    if currencies:
        try:
            online_rates = fetch_online_usd_rates()
            source_note = "使用在线汇率"
            for currency, rate in online_rates.items():
                rate_map[canonical_currency(currency)] = rate
        except Exception:
            source_note = "在线汇率不可用，使用手动或已入库汇率"
            st.warning("在线汇率暂时不可用，可以在页面中手动补充缺失币种汇率。")

    for currency in currencies:
        lookup = canonical_currency(currency)
        rate = rate_map.get(lookup)
        if rate is None:
            default_value = 0.138 if lookup == "CNY" else 1.0
            manual = st.number_input(
                f"{lookup} -> USD 汇率",
                min_value=0.0,
                value=float(default_value),
                format="%.6f",
            )
            rate = FxRate(lookup, "USD", Decimal(str(manual)), date.today(), "manual")
            rate_map[lookup] = rate
        mask = (df["currency"].str.upper() == lookup) & missing
        df.loc[mask, "market_value_usd"] = df.loc[mask, "market_value_original"] * float(rate.rate)

    usd_mask = df["currency"].str.upper() == "USD"
    df.loc[usd_mask & missing, "market_value_usd"] = df.loc[usd_mask & missing, "market_value_original"]
    return df, source_note, rate_map


def add_pnl_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["total_pnl_original"] = df["total_pnl_original"].fillna(df["unrealized_pnl_original"])
    derived = df["market_value_original"] - df["cost_original"]
    df["total_pnl_original"] = df["total_pnl_original"].fillna(derived.where(df["cost_original"].notna()))

    denominator = df["cost_original"].where(df["cost_original"] != 0)
    df["pnl_pct"] = df["pnl_pct"].fillna(df["total_pnl_original"] / denominator)
    df["pnl_pct"] = df["pnl_pct"].replace([float("inf"), -float("inf")], pd.NA)

    ratio = df["market_value_usd"] / df["market_value_original"]
    ratio = ratio.replace([float("inf"), -float("inf")], pd.NA).fillna(1)
    df["cost_usd"] = df["cost_original"] * ratio
    df["total_pnl_usd"] = df["total_pnl_original"] * ratio
    return df


def apply_fund_nav_estimates(
    df: pd.DataFrame,
    fund_navs: pd.DataFrame,
    rate_map: dict[str, FxRate],
) -> pd.DataFrame:
    if df.empty or fund_navs.empty:
        return df

    nav_map = latest_nav_map(fund_navs.to_dict("records"))
    if not nav_map:
        return df

    df = df.copy()
    df["snapshot_price_original"] = df["price_original"]
    df["snapshot_market_value_original"] = df["market_value_original"]
    df["fund_nav_date"] = ""
    df["fund_nav_source"] = ""
    df["fund_nav_status"] = ""

    for index, row in df.iterrows():
        if row.get("asset_type") != "fund":
            continue
        fund_code = normalize_fund_code(str(row.get("symbol") or ""))
        nav = nav_map.get(fund_code)
        quantity = row.get("quantity")
        if nav is None or quantity is None or pd.isna(quantity) or float(quantity) <= 0:
            continue

        estimated_value = float(quantity) * float(nav.unit_nav)
        currency = str(row.get("currency") or "CNY")
        df.at[index, "price_original"] = float(nav.unit_nav)
        df.at[index, "market_value_original"] = estimated_value
        usd_value = convert_amount(estimated_value, currency, "USD", rate_map)
        if usd_value is not None:
            df.at[index, "market_value_usd"] = usd_value
        df.at[index, "fund_nav_date"] = nav.nav_date.isoformat()
        df.at[index, "fund_nav_source"] = nav.source
        df.at[index, "fund_nav_status"] = "latest_nav"
        if not str(row.get("estimate_note") or "").strip():
            df.at[index, "estimate_note"] = "Valued with latest disclosed fund NAV."
        cost = row.get("cost_original")
        if cost is not None and not pd.isna(cost):
            pnl = estimated_value - float(cost)
            df.at[index, "total_pnl_original"] = pnl
            df.at[index, "unrealized_pnl_original"] = pnl
    return df


def convert_amount(
    amount: float | int | None,
    source_currency: str,
    target_currency: str,
    rate_map: dict[str, FxRate],
) -> float | None:
    if amount is None or pd.isna(amount):
        return None

    source = canonical_currency(source_currency)
    target = canonical_currency(target_currency)
    numeric = Decimal(str(amount))

    if source == target:
        return float(numeric)

    if source == "USD":
        usd_amount = numeric
    else:
        source_rate = rate_map.get(source)
        if source_rate is None:
            return None
        usd_amount = numeric * source_rate.rate

    if target == "USD":
        return float(usd_amount)

    target_rate = rate_map.get(target)
    if target_rate is None or target_rate.rate == 0:
        return None
    return float(usd_amount / target_rate.rate)


def add_display_columns(df: pd.DataFrame, display_currency: str, rate_map: dict[str, FxRate]) -> pd.DataFrame:
    df = df.copy()
    df["display_currency"] = display_currency
    df["display_value"] = [
        convert_amount(value, currency, display_currency, rate_map)
        for value, currency in zip(df["market_value_original"], df["currency"])
    ]
    df["display_cost"] = [
        convert_amount(value, currency, display_currency, rate_map)
        for value, currency in zip(df["cost_original"], df["currency"])
    ]
    df["display_pnl"] = [
        convert_amount(value, currency, display_currency, rate_map)
        for value, currency in zip(df["total_pnl_original"], df["currency"])
    ]
    return df


def latest_valuation_date(df: pd.DataFrame) -> str | None:
    dates = [item for item in df["valuation_date"].dropna().tolist() if item]
    if not dates:
        return None
    return str(max(dates))


def currency_symbol(currency: str) -> str:
    return "$" if currency == "USD" else "¥"


def money(value: float | int, currency: str) -> str:
    return f"{currency_symbol(currency)}{float(value):,.2f}"


def number_format(currency: str) -> str:
    return "$%.2f" if currency == "USD" else "¥%.2f"


def percent_text(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:.2f}%"


def metric_money(value: float | None, currency: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    return money(value, currency)


def short_name(value: str, limit: int = 18) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def aggregate_spotlight_positions(df: pd.DataFrame, asset_type: str) -> pd.DataFrame:
    subset = df[df["asset_type"] == asset_type].copy()
    if subset.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "display_name",
                "display_value",
                "display_cost",
                "display_pnl",
                "pnl_pct",
                "holding_count",
            ]
        )

    grouped = subset.groupby(["symbol", "display_name"], as_index=False).agg(
        display_value=("display_value", "sum"),
        display_cost=("display_cost", "sum"),
        display_pnl=("display_pnl", "sum"),
        holding_count=("symbol", "count"),
    )
    denominator = grouped["display_cost"].where(grouped["display_cost"] != 0)
    grouped["pnl_pct"] = grouped["display_pnl"] / denominator
    grouped["pnl_pct"] = grouped["pnl_pct"].replace([float("inf"), -float("inf")], pd.NA)
    grouped["display_name_short"] = grouped["display_name"].apply(short_name)
    return grouped.sort_values("display_value", ascending=False, na_position="last").reset_index(drop=True)


def build_spotlight_chart(grouped: pd.DataFrame, accent: str, display_currency: str) -> go.Figure:
    top = grouped.head(6).sort_values("display_value", ascending=True)
    text_labels = [money(value, display_currency) for value in top["display_value"]]
    customdata = list(
        zip(
            top["symbol"],
            top["display_pnl"].fillna(0),
            top["pnl_pct"].fillna(0),
        )
    )

    fig = go.Figure()
    fig.add_bar(
        x=top["display_value"],
        y=top["display_name_short"],
        orientation="h",
        marker=dict(color=accent, line=dict(color=accent, width=1), opacity=0.92),
        text=text_labels,
        textposition="outside",
        customdata=customdata,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "代码：%{customdata[0]}<br>"
            f"总资金：%{{text}}<br>"
            f"盈亏额：%{{customdata[1]:,.2f}} {display_currency}<br>"
            "盈亏率：%{customdata[2]:.2%}<extra></extra>"
        ),
    )
    fig.update_layout(
        height=280,
        margin=dict(l=8, r=28, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    fig.update_xaxes(
        title=None,
        tickprefix=currency_symbol(display_currency),
        zeroline=False,
    )
    fig.update_yaxes(title=None, showgrid=False)
    return fig


def build_provider_chart(df: pd.DataFrame) -> go.Figure:
    grouped = df.groupby(["provider_label", "currency"], as_index=False)["display_value"].sum()
    grouped = grouped[grouped["display_value"] > 0]
    fig = px.bar(grouped, x="provider_label", y="display_value", color="currency", text_auto=".2s")
    fig.update_layout(
        margin=dict(l=8, r=8, t=8, b=8),
        height=330,
        xaxis_title=None,
        yaxis_title=None,
    )
    return fig


def build_allocation_chart(df: pd.DataFrame) -> go.Figure:
    grouped = df.groupby(["asset_type", "asset_label"], as_index=False)["display_value"].sum()
    grouped = grouped[grouped["display_value"] > 0]
    grouped["sort"] = grouped["asset_type"].apply(lambda item: ASSET_ORDER.index(item) if item in ASSET_ORDER else 99)
    grouped = grouped.sort_values("sort")
    fig = px.pie(grouped, values="display_value", names="asset_label", hole=0.5)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=8, r=8, t=8, b=8), height=340, legend_title_text="")
    return fig


def get_usd_cny_snapshot(rate_map: dict[str, FxRate]) -> dict[str, str] | None:
    rate = rate_map.get("CNY") or rate_map.get("CNH")
    if rate is None or rate.rate == 0:
        return None
    usd_to_cny = (Decimal("1") / rate.rate).quantize(Decimal("0.0001"))
    return {
        "pair": "USD/CNY",
        "value": f"1 USD = {usd_to_cny} CNY",
        "meta": f"{rate.rate_date.isoformat()} · {rate.source}",
    }


def render_hero(df: pd.DataFrame, demo_mode: bool = False) -> None:
    latest_date = latest_valuation_date(df) or "暂无"
    provider_count = int(df["provider"].nunique()) if not df.empty else 0
    positions_count = int(len(df.index))
    mode_badge = "<span class='badge'>演示模式</span>" if demo_mode else ""
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-kicker">Portfolio cockpit</div>
            <div class="hero-title">LXY的Finsight</div>
            <div class="hero-subtitle">适合手机和桌面查看的合并资产看板，汇总盈透证券、汇丰、招商银行和支付宝持仓、币种结构和盈亏变化。</div>
            <div class="badge-row">
                <span class="badge">最新估值 {latest_date}</span>
                <span class="badge">{provider_count} 家机构</span>
                <span class="badge">{positions_count} 条持仓</span>
                <span class="badge">主题跟随系统</span>
                {mode_badge}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_primary_controls(df: pd.DataFrame) -> tuple[str, str]:
    latest_date = latest_valuation_date(df)
    left, right = st.columns([2.7, 1])
    with left:
        st.markdown("<div class='ui-anchor nav-anchor'></div>", unsafe_allow_html=True)
        section = st.segmented_control(
            "浏览模块",
            options=SECTION_OPTIONS,
            default=st.session_state.get("main_section", "总览"),
            key="main_section",
            width="stretch",
            label_visibility="collapsed",
        )
    with right:
        st.markdown("<div class='ui-anchor currency-anchor'></div>", unsafe_allow_html=True)
        display_currency = st.segmented_control(
            "币种",
            options=["USD", "CNY"],
            default=st.session_state.get("display_currency", "USD"),
            format_func=lambda code: code,
            key="display_currency",
            width="stretch",
            label_visibility="collapsed",
        )
    st.caption(f"当前按每个账户的最新快照统计。最新估值日期：{latest_date or '暂无'}")
    return display_currency, section


def query_param_value(name: str) -> str | None:
    try:
        value = st.query_params.get(name)
    except Exception:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def query_param_choice(name: str, options: list[str], default: str) -> str:
    value = query_param_value(name)
    if value in options:
        return value
    stored = st.session_state.get(name)
    if stored in options:
        return str(stored)
    return default


def build_query(**updates: str) -> str:
    params = {
        "section": query_param_value("section") or st.session_state.get("main_section", SECTION_OPTIONS[0]),
        "currency": query_param_value("currency") or st.session_state.get("display_currency", "USD"),
        "provider": query_param_value("provider") or st.session_state.get("provider", "全部"),
        "asset": query_param_value("asset") or st.session_state.get("asset", "全部"),
        "view": query_param_value("view") or st.session_state.get("view", HOLDINGS_VIEW_OPTIONS[0]),
        "sort": query_param_value("sort") or st.session_state.get("sort", HOLDINGS_SORT_OPTIONS[0]),
    }
    params.update({key: value for key, value in updates.items() if value is not None})
    return "?" + urlencode(params)


def render_sidebar_nav(active_section: str, display_currency: str) -> None:
    items = []
    for section in SECTION_OPTIONS:
        params = urlencode({"section": section, "currency": display_currency})
        active_class = " active" if section == active_section else ""
        icon = NAV_ICON_SVGS.get(section, "")
        items.append(
            f"<a class='sidebar-nav-item{active_class}' href='?{params}' target='_self'>"
            f"{icon}<span class='sidebar-nav-label'>{section}</span>"
            "</a>"
        )
    st.markdown(
        (
            "<nav class='sidebar-nav' aria-label='浏览'>"
            "<div class='sidebar-nav-title'>浏览</div>"
            "<div class='sidebar-nav-list'>"
            + "".join(items)
            + "</div></nav>"
        ),
        unsafe_allow_html=True,
    )


def render_filter_nav(title: str, param_name: str, options: list[str], active: str) -> None:
    items = []
    for option in options:
        active_class = " active" if option == active else ""
        href = build_query(**{param_name: option})
        items.append(f"<a class='filter-nav-item{active_class}' href='{href}' target='_self'>{option}</a>")
    st.markdown(
        (
            f"<div class='filter-nav' style='--filter-count:{len(options)}'>"
            f"<div class='filter-nav-title'>{title}</div>"
            "<div class='filter-nav-list'>"
            + "".join(items)
            + "</div></div>"
        ),
        unsafe_allow_html=True,
    )


def render_sidebar_currency(active_currency: str, section: str) -> None:
    items = []
    for currency in ("USD", "CNY"):
        params = urlencode({"section": section, "currency": currency})
        active_class = " active" if currency == active_currency else ""
        icon = NAV_ICON_SVGS.get(currency, "")
        items.append(
            f"<a class='sidebar-nav-item{active_class}' href='?{params}' target='_self'>"
            f"{icon}<span class='sidebar-nav-label'>{currency}</span>"
            "</a>"
        )
    st.markdown(
        (
            "<nav class='sidebar-nav' aria-label='币种'>"
            "<div class='sidebar-nav-title'>币种</div>"
            "<div class='sidebar-nav-list'>"
            + "".join(items)
            + "</div></nav>"
        ),
        unsafe_allow_html=True,
    )


def build_query(**updates: str) -> str:
    params = {
        "section": query_param_value("section") or st.session_state.get("main_section", SECTION_OPTIONS[0]),
        "currency": query_param_value("currency") or st.session_state.get("display_currency", "USD"),
        "provider": query_param_value("provider") or st.session_state.get("provider", "全部"),
        "asset": query_param_value("asset") or st.session_state.get("asset", "全部"),
        "view": query_param_value("view") or st.session_state.get("view", HOLDINGS_VIEW_OPTIONS[0]),
        "sort": query_param_value("sort") or st.session_state.get("sort", HOLDINGS_SORT_OPTIONS[0]),
        AUTH_QUERY_TOKEN: query_param_value(AUTH_QUERY_TOKEN),
        AUTH_QUERY_EXPIRES: query_param_value(AUTH_QUERY_EXPIRES),
    }
    params.update({key: value for key, value in updates.items() if value is not None})
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    return "?" + urlencode(clean_params)


def render_sidebar_nav(active_section: str, display_currency: str) -> None:
    items = []
    for section in SECTION_OPTIONS:
        params = build_query(section=section, currency=display_currency)
        active_class = " active" if section == active_section else ""
        icon = NAV_ICON_SVGS.get(section, "")
        items.append(
            f"<a class='sidebar-nav-item{active_class}' href='{params}' target='_self'>"
            f"{icon}<span class='sidebar-nav-label'>{section}</span>"
            "</a>"
        )
    st.markdown(
        (
            "<nav class='sidebar-nav' aria-label='浏览'>"
            "<div class='sidebar-nav-title'>浏览</div>"
            "<div class='sidebar-nav-list'>"
            + "".join(items)
            + "</div></nav>"
        ),
        unsafe_allow_html=True,
    )


def render_sidebar_currency(active_currency: str, section: str) -> None:
    items = []
    for currency in ("USD", "CNY"):
        params = build_query(section=section, currency=currency)
        active_class = " active" if currency == active_currency else ""
        icon = NAV_ICON_SVGS.get(currency, "")
        items.append(
            f"<a class='sidebar-nav-item{active_class}' href='{params}' target='_self'>"
            f"{icon}<span class='sidebar-nav-label'>{currency}</span>"
            "</a>"
        )
    st.markdown(
        (
            "<nav class='sidebar-nav' aria-label='币种'>"
            "<div class='sidebar-nav-title'>币种</div>"
            "<div class='sidebar-nav-list'>"
            + "".join(items)
            + "</div></nav>"
        ),
        unsafe_allow_html=True,
    )


def render_sidebar_controls(df: pd.DataFrame) -> tuple[str, str]:
    latest_date = latest_valuation_date(df)
    with st.sidebar:
        st.markdown(
            "<div class='sidebar-block'><div class='sidebar-kicker'>Navigation</div><div class='sidebar-brand'>LXY的Finsight</div><div class='sidebar-subtitle'>资产、结构、持仓和同步操作</div></div>",
            unsafe_allow_html=True,
        )
        current_fx = st.session_state.get("usd_cny_snapshot")
        if current_fx:
            st.markdown(
                (
                    "<div class='sidebar-fx'>"
                    "<div class='sidebar-fx-label'>美元兑人民币</div>"
                    f"<div class='sidebar-fx-value'>{current_fx['value']}</div>"
                    f"<div class='sidebar-fx-meta'>{current_fx['meta']}</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
        query_section = query_param_value("section")
        section_default = query_section if query_section in SECTION_OPTIONS else st.session_state.get("main_section", SECTION_OPTIONS[0])
        section = section_default if section_default in SECTION_OPTIONS else SECTION_OPTIONS[0]
        query_currency = query_param_value("currency")
        display_default = query_currency if query_currency in {"USD", "CNY"} else st.session_state.get("display_currency", "USD")
        render_sidebar_nav(section, display_default)
        display_currency = display_default if display_default in {"USD", "CNY"} else "USD"
        render_sidebar_currency(display_currency, section)
        st.session_state["main_section"] = section
        st.session_state["display_currency"] = display_currency
        st.caption(f"最新估值日期：{latest_date or '暂无'}")
    return display_currency, section


def render_metrics(df: pd.DataFrame, display_currency: str) -> None:
    total_value = df["display_value"].sum(skipna=True)
    total_pnl = df["display_pnl"].sum(skipna=True)

    top = st.columns(2)
    top[0].metric(f"总资产 {display_currency}", money(total_value, display_currency))
    top[1].metric(f"已识别盈亏 {display_currency}", money(total_pnl, display_currency))
    provider_cols = st.columns(4)
    for column, label in zip(provider_cols, PROVIDER_ORDER):
        provider_total = df[df["provider_label"] == label]["display_value"].sum(skipna=True)
        column.metric(label, money(provider_total, display_currency))


def render_spotlight_panel(df: pd.DataFrame, spec: dict[str, str], display_currency: str) -> None:
    grouped = aggregate_spotlight_positions(df, spec["asset_type"])
    total_value = grouped["display_value"].sum(skipna=True)
    total_pnl = grouped["display_pnl"].sum(skipna=True)
    total_cost = grouped["display_cost"].sum(skipna=True)
    total_pct = total_pnl / total_cost if total_cost else None
    pnl_available = grouped["display_pnl"].notna().any()
    cost_available = grouped["display_cost"].notna().any()
    total_pnl_display = total_pnl if pnl_available else None
    total_pct_display = total_pct if pnl_available and cost_available else None
    accent = spec["accent"]
    card_class = spec.get("card_class", "")
    metrics_html = (
        f"<div class='spotlight-metrics'>"
        f"<div class='spotlight-metric'><div class='spotlight-metric-label'>总资金</div><div class='spotlight-metric-value'>{money(total_value, display_currency)}</div></div>"
        f"<div class='spotlight-metric'><div class='spotlight-metric-label'>盈亏额</div><div class='spotlight-metric-value'>{metric_money(total_pnl_display, display_currency)}</div></div>"
        f"<div class='spotlight-metric'><div class='spotlight-metric-label'>盈亏率</div><div class='spotlight-metric-value'>{percent_text(total_pct_display)}</div></div>"
        f"</div>"
    )
    st.markdown(
        (
            f"<div class='spotlight-shell {card_class}' style='--spot-accent:{accent};'>"
            f"<div class='spotlight-title'>{spec['title']}</div>"
            f"<div class='spotlight-subtitle'>{spec['subtitle']}</div>"
            f"<span class='spotlight-chip'>持仓 {len(grouped)} 项</span>"
            f"<span class='spotlight-chip'>统计币种 {display_currency}</span>"
            f"{metrics_html}"
            f"</div>"
        ),
        unsafe_allow_html=True,
    )
    if grouped.empty:
        st.info(f"当前还没有可展示的{spec['title']}持仓。")
    else:
        st.plotly_chart(
            build_spotlight_chart(grouped, spec["accent"], display_currency),
            use_container_width=True,
            theme="streamlit",
            config=PLOTLY_CONFIG,
        )


def render_spotlight_panels(df: pd.DataFrame, display_currency: str) -> None:
    st.markdown("<div class='section-title'>专题看板</div>", unsafe_allow_html=True)
    st.markdown("<div class='section-subtitle'>按资产组快速浏览规模、盈亏和代表性持仓，更适合手机上单屏扫读。</div>", unsafe_allow_html=True)
    for spec in PANEL_SPECS:
        render_spotlight_panel(df, spec, display_currency)


def render_allocation(df: pd.DataFrame, display_currency: str) -> None:
    st.markdown("<div class='section-title'>结构图</div>", unsafe_allow_html=True)
    allocation_fig = build_allocation_chart(df)
    provider_fig = build_provider_chart(df)
    st.plotly_chart(allocation_fig, use_container_width=True, theme="streamlit", config=PLOTLY_CONFIG)
    st.plotly_chart(provider_fig, use_container_width=True, theme="streamlit", config=PLOTLY_CONFIG)


def render_summary_tables(df: pd.DataFrame, display_currency: str) -> None:
    st.markdown("<div class='section-title'>汇总视图</div>", unsafe_allow_html=True)
    summary_mode = st.segmented_control(
        "汇总方式",
        options=SUMMARY_OPTIONS,
        default=st.session_state.get("summary_mode", "按机构"),
        key="summary_mode",
        width="stretch",
    )
    mapping = {
        "按机构": (["provider_label"], {"provider_label": "机构"}),
        "按币种": (["currency"], {"currency": "币种"}),
        "按资产": (["asset_label"], {"asset_label": "资产类型"}),
    }
    group_cols, labels = mapping[summary_mode]
    show_summary(df, group_cols, labels, display_currency)


def show_summary(df: pd.DataFrame, group_cols: list[str], labels: dict[str, str], display_currency: str) -> None:
    grouped = df.groupby(group_cols, as_index=False).agg(
        display_value=("display_value", "sum"),
        display_pnl=("display_pnl", "sum"),
        rows=("instrument_name", "count"),
    )
    total = grouped["display_value"].sum() or 1
    grouped["weight"] = grouped["display_value"] / total

    value_column = f"市值 {display_currency}"
    pnl_column = f"盈亏 {display_currency}"
    view = grouped.rename(
        columns={
            **labels,
            "display_value": value_column,
            "display_pnl": pnl_column,
            "rows": "持仓数",
            "weight": "占比",
        }
    )
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            value_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            pnl_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            "占比": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=1),
        },
    )


def asset_filter_options(df: pd.DataFrame) -> list[str]:
    return ["全部"] + [ASSET_LABELS[key] for key in ASSET_ORDER if key in set(df["asset_type"])]


def filter_positions(
    df: pd.DataFrame,
    selected_provider: str,
    selected_asset: str,
    search_text: str,
    sort_mode: str,
) -> pd.DataFrame:
    filtered = df.copy()
    if selected_provider != "全部":
        filtered = filtered[filtered["provider_label"] == selected_provider]
    if selected_asset != "全部":
        reverse = {label: key for key, label in ASSET_LABELS.items()}
        filtered = filtered[filtered["asset_type"] == reverse.get(selected_asset)]
    if search_text:
        lowered = search_text.strip().lower()
        haystack = (
            filtered["symbol"].fillna("").astype(str).str.lower()
            + " "
            + filtered["instrument_name"].fillna("").astype(str).str.lower()
            + " "
            + filtered["display_name"].fillna("").astype(str).str.lower()
        )
        filtered = filtered[haystack.str.contains(lowered, regex=False)]

    sort_map = {
        "金额↓": (["display_value", "provider_label", "account_name", "symbol"], [False, True, True, True]),
        "金额↑": (["display_value", "provider_label", "account_name", "symbol"], [True, True, True, True]),
        "盈亏率↓": (["pnl_pct", "display_value", "provider_label", "symbol"], [False, False, True, True]),
        "盈亏率↑": (["pnl_pct", "display_value", "provider_label", "symbol"], [True, False, True, True]),
    }
    sort_by, ascending = sort_map.get(sort_mode, sort_map["金额↓"])
    return filtered.sort_values(by=sort_by, ascending=ascending, na_position="last").reset_index(drop=True)


def render_holdings_header(df: pd.DataFrame, display_currency: str) -> tuple[pd.DataFrame, int]:
    st.markdown("<div class='section-title'>持仓详情</div>", unsafe_allow_html=True)
    st.markdown("<div class='section-subtitle'>默认提供更适合手机的卡片视图；如果你在桌面上工作，也可以一键切回表格。</div>", unsafe_allow_html=True)

    providers = provider_filter_options(df)
    provider = st.segmented_control(
        "机构筛选",
        options=providers,
        default=st.session_state.get("holdings_provider", "全部") if st.session_state.get("holdings_provider", "全部") in providers else "全部",
        key="holdings_provider",
        width="stretch",
    )
    asset_options = asset_filter_options(df)
    asset = st.segmented_control(
        "资产筛选",
        options=asset_options,
        default=st.session_state.get("holdings_asset", "全部") if st.session_state.get("holdings_asset", "全部") in asset_options else "全部",
        key="holdings_asset",
        width="stretch",
    )
    c1, c2 = st.columns([1.2, 1])
    with c1:
        search_text = st.text_input("搜索代码或名称", value=st.session_state.get("holdings_search", ""), key="holdings_search")
    with c2:
        view_mode = st.segmented_control(
            "展示方式",
            options=HOLDINGS_VIEW_OPTIONS,
            default=st.session_state.get("holdings_view_mode", "卡片"),
            key="holdings_view_mode",
            width="stretch",
        )
    sort_mode = st.segmented_control(
        "排序方式",
        options=HOLDINGS_SORT_OPTIONS,
        default=st.session_state.get("holdings_sort_mode", "金额↓"),
        key="holdings_sort_mode",
        width="stretch",
    )

    filtered = filter_positions(df, provider, asset, search_text, sort_mode)
    total_value = filtered["display_value"].sum(skipna=True)
    total_pnl = filtered["display_pnl"].sum(skipna=True)
    st.caption(f"当前筛选结果：{len(filtered)} 条，市值 {money(total_value, display_currency)}，盈亏 {metric_money(total_pnl, display_currency)}。")
    return filtered, 8 if view_mode == "卡片" else 15


def render_holdings_header(df: pd.DataFrame, display_currency: str) -> tuple[pd.DataFrame, int]:
    st.markdown("<div class='section-title'>持仓详情</div>", unsafe_allow_html=True)
    st.markdown("<div class='section-subtitle'>默认提供更适合手机的卡片视图；如果你在桌面上工作，也可以一键切回表格。</div>", unsafe_allow_html=True)

    providers = provider_filter_options(df)
    provider = query_param_choice("provider", providers, "全部")
    render_filter_nav("机构筛选", "provider", providers, provider)

    asset_options = asset_filter_options(df)
    asset = query_param_choice("asset", asset_options, "全部")
    render_filter_nav("资产筛选", "asset", asset_options, asset)

    c1, c2 = st.columns([1.2, 1])
    with c1:
        search_text = st.text_input("搜索代码或名称", value=st.session_state.get("holdings_search", ""), key="holdings_search")
    with c2:
        view_mode = query_param_choice("view", HOLDINGS_VIEW_OPTIONS, "卡片")
        render_filter_nav("展示方式", "view", HOLDINGS_VIEW_OPTIONS, view_mode)

    sort_mode = query_param_choice("sort", HOLDINGS_SORT_OPTIONS, HOLDINGS_SORT_OPTIONS[0])
    render_filter_nav("排序方式", "sort", HOLDINGS_SORT_OPTIONS, sort_mode)

    st.session_state["holdings_provider"] = provider
    st.session_state["holdings_asset"] = asset
    st.session_state["holdings_view_mode"] = view_mode
    st.session_state["holdings_sort_mode"] = sort_mode

    filtered = filter_positions(df, provider, asset, search_text, sort_mode)
    total_value = filtered["display_value"].sum(skipna=True)
    total_pnl = filtered["display_pnl"].sum(skipna=True)
    st.caption(f"当前筛选结果：{len(filtered)} 条，市值 {money(total_value, display_currency)}，盈亏 {metric_money(total_pnl, display_currency)}。")
    return filtered, 8 if view_mode == "卡片" else 15


def holding_pnl_class(pnl_pct: float | None) -> str:
    if pnl_pct is None or pd.isna(pnl_pct):
        return ""
    return "pnl-up" if pnl_pct > 0 else "pnl-down" if pnl_pct < 0 else ""


def render_holdings_cards(filtered: pd.DataFrame, display_currency: str, page_size: int) -> None:
    if filtered.empty:
        st.info("当前筛选下没有可展示的持仓。")
        return

    st.caption(f"共 {len(filtered)} 条，向下滚动即可连续查看。")

    for _, row in filtered.iterrows():
        pnl_cls = holding_pnl_class(row.get("pnl_pct"))
        pnl_text = percent_text(row.get("pnl_pct"))
        asset_type = row.get("asset_type")
        quantity_label = "克数" if asset_type == "gold" else "数量"
        price_label = "金价" if asset_type == "gold" else "单价"
        pnl_amount_text = metric_money(row.get("display_pnl", 0) or 0, display_currency)
        nav_meta = ""
        if row.get("fund_nav_date"):
            nav_meta = f" · 净值日期：{row.get('fund_nav_date')} · 份额来源：{row.get('quantity_source', 'reported')}"
        st.markdown(
            f"""
            <div class="holding-card">
                <div class="holding-header">
                    <div>
                        <div class="holding-name">{row.get("display_name") or row.get("instrument_name") or row.get("symbol")}</div>
                        <div class="holding-code">{row.get("symbol", "")} · {row.get("provider_label", row.get("provider", ""))} · {row.get("asset_label", "")}</div>
                    </div>
                    <div class="holding-value">
                        <div class="holding-value-main">{money(row.get("display_value", 0) or 0, display_currency)}</div>
                        <div class="holding-value-sub">{row.get("currency", "")} 原币 {float(row.get("market_value_original", 0) or 0):,.2f}</div>
                    </div>
                </div>
                <div class="holding-grid">
                    <div>
                        <div class="mini-label">{quantity_label}</div>
                        <div class="mini-value">{float(row.get("quantity", 0) or 0):,.4f}</div>
                    </div>
                    <div>
                        <div class="mini-label">{price_label}</div>
                        <div class="mini-value">{float(row.get("price_original", 0) or 0):,.4f}</div>
                    </div>
                    <div>
                        <div class="mini-label">原币成本</div>
                        <div class="mini-value">{float(row.get("cost_original", 0) or 0):,.2f}</div>
                    </div>
                    <div>
                        <div class="mini-label">盈亏</div>
                        <div class="mini-value pnl-rate {pnl_cls}">{pnl_amount_text}</div>
                    </div>
                    <div>
                        <div class="mini-label">盈亏率</div>
                        <div class="mini-value pnl-rate {pnl_cls}">{pnl_text}</div>
                    </div>
                </div>
                <div class="tiny-note">账户：{row.get("account_name", "")} · 估值日期：{row.get("valuation_date", "")}{nav_meta}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_holdings_table(filtered: pd.DataFrame, display_currency: str, page_size: int) -> None:
    total_rows = len(filtered)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = st.number_input("表格页码", min_value=1, max_value=total_pages, value=1, step=1)
    page_df = filtered.iloc[(page - 1) * page_size : page * page_size].copy()

    summary_row = {
        "provider_label": "汇总",
        "account_name": "",
        "asset_label": "",
        "symbol": "",
        "display_name": "",
        "quantity": pd.NA,
        "price_original": pd.NA,
        "market_value_original": filtered["market_value_original"].sum(skipna=True),
        "currency": "多币种",
        "display_value": filtered["display_value"].sum(skipna=True),
        "cost_original": filtered["cost_original"].sum(skipna=True),
        "display_pnl": filtered["display_pnl"].sum(skipna=True),
        "pnl_pct": pd.NA,
        "valuation_date": "",
        "fund_nav_date": "",
        "quantity_source": "",
    }
    page_df = pd.concat([page_df, pd.DataFrame([summary_row])], ignore_index=True)

    value_column = f"折算市值 {display_currency}"
    pnl_column = f"折算盈亏 {display_currency}"
    view = page_df[
        [
            "provider_label",
            "account_name",
            "asset_label",
            "symbol",
            "display_name",
            "quantity",
            "price_original",
            "market_value_original",
            "currency",
            "display_value",
            "cost_original",
            "display_pnl",
            "pnl_pct",
            "valuation_date",
            "fund_nav_date",
            "quantity_source",
        ]
    ].rename(
        columns={
            "provider_label": "机构",
            "account_name": "账户",
            "asset_label": "资产类型",
            "symbol": "代码",
            "display_name": "名称",
            "quantity": "数量/克数",
            "price_original": "单价/金价",
            "market_value_original": "原币市值",
            "currency": "币种",
            "display_value": value_column,
            "cost_original": "原币成本",
            "display_pnl": pnl_column,
            "pnl_pct": "盈亏率",
            "valuation_date": "估值日期",
            "fund_nav_date": "净值日期",
            "quantity_source": "份额来源",
        }
    )
    view["盈亏率"] = view["盈亏率"] * 100
    st.caption(f"第 {page} / {total_pages} 页，共 {total_rows} 条。表格末行显示当前筛选结果的汇总。")
    st.dataframe(
        style_positions_table(view),
        use_container_width=True,
        hide_index=True,
        column_config={
            "数量/克数": st.column_config.NumberColumn(format="%.4f"),
            "单价/金价": st.column_config.NumberColumn(format="%.4f"),
            "原币市值": st.column_config.NumberColumn(format="%.2f"),
            value_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            "原币成本": st.column_config.NumberColumn(format="%.2f"),
            pnl_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            "盈亏率": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )


def render_holdings(df: pd.DataFrame, display_currency: str) -> None:
    filtered, page_size = render_holdings_header(df, display_currency)
    if st.session_state.get("holdings_view_mode", "卡片") == "卡片":
        render_holdings_cards(filtered, display_currency, page_size)
    else:
        render_holdings_table(filtered, display_currency, page_size)


def style_positions_table(view: pd.DataFrame):
    def row_style(row: pd.Series) -> list[str]:
        institution = str(row.get("机构") or "")
        pnl_pct = row.get("盈亏率")
        if institution == "汇总" or pd.isna(pnl_pct):
            return [""] * len(row)
        if pnl_pct > 0:
            return ["background-color: #cfeedd"] * len(row)
        if pnl_pct < 0:
            return ["background-color: #f6d1d1"] * len(row)
        return [""] * len(row)

    return view.style.apply(row_style, axis=1)


def render_import_status(imports: pd.DataFrame, errors: pd.DataFrame) -> None:
    with st.expander("最近导入记录"):
        st.dataframe(imports, use_container_width=True, hide_index=True)
    with st.expander("待处理问题"):
        if errors.empty:
            st.success("暂无导入错误。")
        else:
            st.dataframe(errors, use_container_width=True, hide_index=True)


def can_write_from_dashboard(settings: Settings) -> bool:
    return settings.has_supabase_write_config


def sync_ibkr_via_dashboard(account: str, settings: Settings) -> str:
    client = get_supabase(use_service_role=True, settings=settings)
    sync_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    import_id = create_import_record(
        client,
        source="ibkr",
        source_type="api",
        file_name=None,
        file_hash=f"ibkr-{account}-{sync_started_at}",
    )

    try:
        data = sync_ibkr_data(account=account, settings=settings)
        for account_name in data.accounts:
            summary = data.account_summaries.get(account_name, {})
            upsert_account(client, "IBKR", account_name, summary.get("BaseCurrency", "USD") or "USD")

        imported = import_normalized_rows(client, data.rows, import_id)
        if imported == len(data.rows):
            complete_import(client, import_id, imported, "completed")
        else:
            failed = len(data.rows) - imported
            complete_import(client, import_id, imported, "needs_review", f"{failed} rows failed during import.")
        return f"IBKR 同步完成：{imported}/{len(data.rows)} 条，覆盖 {len(data.accounts)} 个账户。"
    except Exception as exc:
        log_import_error(client, import_id, None, {"account": account}, str(exc))
        complete_import(client, import_id, 0, "failed", str(exc))
        raise RuntimeError(f"IBKR 同步失败：{exc}") from exc


def _printable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def preview_rows_frame(rows: list[object]) -> pd.DataFrame:
    return pd.DataFrame([{key: _printable(value) for key, value in asdict(row).items()} for row in rows])


def import_hsbc_pdf_via_dashboard(file_name: str, pdf_bytes: bytes, settings: Settings, dry_run: bool) -> tuple[str, pd.DataFrame]:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
        handle.write(pdf_bytes)
        temp_path = Path(handle.name)

    try:
        rows = parse_hsbc_cn_pdf(temp_path)
        preview = preview_rows_frame(rows)

        if dry_run:
            return f"预检完成：识别到 {len(rows)} 条记录。", preview

        client = get_supabase(use_service_role=True, settings=settings)
        import_id = create_import_record(
            client,
            source="hsbc_china",
            source_type="pdf",
            file_name=file_name,
            file_hash=file_sha256(temp_path),
        )
        if not rows:
            log_import_error(
                client,
                import_id,
                None,
                {"file_name": file_name},
                "No recognizable HSBC China rows found. Add a desensitized sample PDF to improve parser rules.",
            )
            complete_import(client, import_id, 0, "needs_review", "No recognizable rows found.")
            raise RuntimeError("没有识别到可导入的数据，这次导入已标记为 needs_review。")

        imported = import_normalized_rows(client, rows, import_id)
        complete_import(client, import_id, imported, "completed")
        return f"汇丰 PDF 导入完成：{imported} 条。", preview
    finally:
        temp_path.unlink(missing_ok=True)


def render_hsbc_preview() -> None:
    preview = st.session_state.get(HSBC_PREVIEW_KEY)
    file_name = st.session_state.get(HSBC_PREVIEW_NAME_KEY)
    if preview is None or not isinstance(preview, pd.DataFrame) or preview.empty:
        return
    with st.expander(f"最近一次 PDF 预检：{file_name}", expanded=False):
        st.dataframe(preview, use_container_width=True, hide_index=True)


def fund_codes_from_manual_position_records(records: list[dict[str, str]]) -> list[str]:
    codes = []
    for raw in records:
        asset_type = str(raw.get("asset_type") or "").strip()
        quantity = str(raw.get("quantity") or "").strip()
        amount = str(raw.get("amount") or "").strip()
        fund_code = normalize_fund_code(str(raw.get("instrument_code") or ""))
        if fund_code and asset_type == "fund" and amount and not quantity:
            codes.append(fund_code)
    return sorted(set(codes))


def fetch_fund_navs_for_codes(codes: list[str], settings: Settings) -> dict[str, FundNav]:
    if not codes:
        return {}
    provider = EastmoneyFundNavProvider(settings=settings)
    return provider.fetch_many(codes)


def fund_codes_from_normalized_rows(rows: list[object]) -> list[str]:
    codes = []
    for row in rows:
        if getattr(row, "asset_type", "") != "fund":
            continue
        code = normalize_fund_code(str(getattr(row, "instrument_code", "") or ""))
        if code:
            codes.append(code)
    return sorted(set(codes))


def build_manual_position_rows(source_label: str, records: list[dict[str, str]], settings: Settings | None = None) -> list[object]:
    source = MANUAL_POSITION_SOURCES[source_label]
    settings = settings or get_settings()
    fund_navs = fetch_fund_navs_for_codes(fund_codes_from_manual_position_records(records), settings)
    return parse_manual_position_records(
        records,
        provider=source["provider"],
        account_name=source["account_name"],
        valuation_date=date.today(),
        fund_navs=fund_navs,
    )


def _safe_draft_filename(name: str, fallback: str) -> str:
    raw_name = Path(name or fallback).name or fallback
    safe = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in raw_name)
    return safe.strip("._") or fallback


def save_manual_position_draft(
    source_label: str,
    uploaded_files: list[dict[str, object]],
    records: list[dict[str, str]],
    rows: list[object] | None = None,
    error: Exception | str | None = None,
    status: str | None = None,
) -> Path:
    created_at = datetime.now(timezone.utc).replace(microsecond=0)
    digest = hashlib.sha256(
        json.dumps(records, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
        + b"|"
        + "|".join(str(item.get("name") or "") for item in uploaded_files).encode("utf-8")
    ).hexdigest()[:10]
    draft_dir = MANUAL_POSITION_DRAFT_DIR / f"{created_at.strftime('%Y%m%d-%H%M%S')}-{digest}"
    draft_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for index, item in enumerate(uploaded_files, start=1):
        file_name = _safe_draft_filename(str(item.get("name") or ""), f"screenshot-{index}.png")
        target = draft_dir / f"{index:02d}-{file_name}"
        target.write_bytes(bytes(item.get("bytes") or b""))
        saved_files.append(
            {
                "original_name": item.get("name"),
                "saved_path": str(target),
                "mime_type": item.get("mime_type"),
                "size": len(bytes(item.get("bytes") or b"")),
            }
        )

    payload = {
        "created_at": created_at.isoformat(),
        "source_label": source_label,
        "default_asset_type": MANUAL_POSITION_SOURCES.get(source_label, {}).get("default_asset_type", ""),
        "review_hint": MANUAL_POSITION_SOURCES.get(source_label, {}).get("draft_hint", ""),
        "files": saved_files,
        "recognized_records": records,
        "normalized_rows": preview_rows_frame(rows).to_dict("records") if rows else [],
        "error": str(error) if error else "",
        "status": status or ("needs_review" if error else "recognized"),
    }
    (draft_dir / "draft.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return draft_dir


def uploaded_images_to_draft_files(uploaded_images: list[object]) -> list[dict[str, object]]:
    uploaded_files: list[dict[str, object]] = []
    for uploaded_image in uploaded_images:
        uploaded_files.append(
            {
                "name": uploaded_image.name,
                "mime_type": uploaded_image.type,
                "bytes": uploaded_image.getvalue(),
            }
        )
    return uploaded_files


def save_manual_position_upload_draft(source_label: str, uploaded_images: list[object]) -> Path:
    draft_path = save_manual_position_draft(
        source_label,
        uploaded_images_to_draft_files(uploaded_images),
        records=[],
        status="awaiting_manual_review",
    )
    mark_manual_position_draft_for_codex(draft_path)
    return draft_path


def list_manual_position_drafts() -> list[Path]:
    if not MANUAL_POSITION_DRAFT_DIR.exists():
        return []
    return sorted(
        [item for item in MANUAL_POSITION_DRAFT_DIR.iterdir() if item.is_dir() and (item / "draft.json").exists()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def read_manual_position_draft(draft_dir: Path) -> dict[str, Any]:
    return json.loads((draft_dir / "draft.json").read_text(encoding="utf-8"))


def draft_display_label(draft_dir: Path) -> str:
    try:
        payload = read_manual_position_draft(draft_dir)
    except Exception:
        return draft_dir.name
    source = str(payload.get("source_label") or "未知来源")
    status = str(payload.get("status") or "unknown")
    if corrected_records_path(draft_dir).exists():
        status = "已校正可导入"
    elif codex_request_path(draft_dir).exists():
        status = "已请求 Codex 校正"
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    file_count = len(files)
    return f"{draft_dir.name} · {source} · {file_count} 张 · {status}"


def corrected_records_path(draft_dir: Path) -> Path:
    return draft_dir / "corrected_records.json"


def codex_request_path(draft_dir: Path) -> Path:
    return draft_dir / "codex_request.json"


def mark_manual_position_draft_for_codex(draft_dir: Path) -> Path:
    try:
        draft_payload = read_manual_position_draft(draft_dir)
    except Exception:
        draft_payload = {}
    source_label = str(draft_payload.get("source_label") or "")
    review_hint = str(draft_payload.get("review_hint") or "")
    instruction = "请读取本草稿目录中的持仓截图，人工校正为 corrected_records.json。"
    if source_label:
        instruction += f" 截图来源：{source_label}。"
    if review_hint:
        instruction += f" {review_hint}"
    payload = {
        "requested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "requested",
        "instruction": instruction,
    }
    target = codex_request_path(draft_dir)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    draft_json = draft_dir / "draft.json"
    if draft_json.exists():
        try:
            draft_payload["status"] = "codex_requested"
            draft_payload["codex_request"] = str(target)
            draft_json.write_text(json.dumps(draft_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    return target


def load_corrected_manual_position_records(draft_dir: Path) -> list[dict[str, str]]:
    records = json.loads(corrected_records_path(draft_dir).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("corrected_records.json must contain a JSON list.")
    return [item for item in records if isinstance(item, dict)]


def manual_position_import_hash(source: str, rows: list[object]) -> str:
    payload = preview_rows_frame(rows).to_dict("records")
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    imported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return hashlib.sha256(f"{source}:{imported_at}:{raw}".encode("utf-8")).hexdigest()


def refresh_fund_navs_for_imported_rows(client: object, rows: list[object], settings: Settings) -> str:
    codes = fund_codes_from_normalized_rows(rows)
    if not codes:
        return ""
    navs = list(fetch_fund_navs_for_codes(codes, settings).values())
    ok_count = sum(1 for nav in navs if nav.status == "ok")
    try:
        loaded = upsert_fund_navs(client, navs)
    except MissingFundNavTable:
        return "基金净值未写入：Supabase 还没有 fund_navs 表。"
    return f"基金净值已刷新：成功 {ok_count}/{len(codes)} 个，写入 {loaded} 条。"


def import_manual_positions_via_dashboard(
    source_label: str,
    rows: list[object],
    settings: Settings,
    file_names: list[str] | None = None,
) -> str:
    source = MANUAL_POSITION_SOURCES[source_label]
    file_name = ", ".join(file_names or []) or f"{source_label}-{date.today().isoformat()}"
    client = get_supabase(use_service_role=True, settings=settings)
    import_id = create_import_record(
        client,
        source=source["source"],
        source_type="position_screenshot",
        file_name=file_name,
        file_hash=manual_position_import_hash(source["source"], rows),
    )
    nav_message = refresh_fund_navs_for_imported_rows(client, rows, settings)
    imported = import_normalized_rows(client, rows, import_id)
    if imported == len(rows):
        complete_import(client, import_id, imported, "completed")
    else:
        failed = len(rows) - imported
        complete_import(client, import_id, imported, "needs_review", f"{failed} rows failed during import.")
    message = f"{source_label} 持仓导入完成：{imported}/{len(rows)} 条。"
    return f"{message} {nav_message}".strip()


def render_manual_positions_import(settings: Settings) -> None:
    st.divider()
    st.markdown("#### 招商/支付宝/黄金截图草稿箱")
    source_label = st.selectbox(
        "选择截图来源",
        options=list(MANUAL_POSITION_SOURCES),
        key="manual_position_source",
    )
    uploaded_images = st.file_uploader(
        "上传持仓截图",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="manual_position_screenshot_uploader",
    )
    st.caption("上传后只保存原图草稿，不再调用视觉识别接口。草稿被校正后，可在这里直接预览并导入。")

    preview_col, import_col = st.columns(2)
    with preview_col:
        if st.button(
            "保存截图草稿",
            key="preview_manual_positions",
            icon=":material/save:",
            use_container_width=True,
            disabled=not uploaded_images,
        ):
            try:
                draft_path = save_manual_position_upload_draft(source_label, uploaded_images)
                st.success("截图草稿已保存。")
                st.caption(f"草稿目录：{draft_path}")
            except Exception as exc:
                st.error(str(exc))

    draft_dirs = list_manual_position_drafts()
    selected_draft: Path | None = None
    corrected_records: list[dict[str, str]] = []
    rows: list[object] = []
    draft_payload: dict[str, Any] = {}
    if draft_dirs:
        selected_label = st.selectbox(
            "选择要导入的校正草稿",
            options=[str(item) for item in draft_dirs],
            format_func=lambda value: draft_display_label(Path(value)),
            key="manual_position_selected_draft",
        )
        selected_draft = Path(selected_label)
        draft_payload = read_manual_position_draft(selected_draft)
        st.caption(f"当前草稿目录：{selected_draft}")
        if corrected_records_path(selected_draft).exists():
            try:
                corrected_records = load_corrected_manual_position_records(selected_draft)
                draft_source_label = str(draft_payload.get("source_label") or source_label)
                if draft_source_label not in MANUAL_POSITION_SOURCES:
                    draft_source_label = source_label
                rows = build_manual_position_rows(draft_source_label, corrected_records, settings)
                st.success(f"已发现校正文件：{corrected_records_path(selected_draft).name}，可导入 {len(rows)} 条。")
            except Exception as exc:
                st.error(f"校正文件无法解析：{exc}")
        else:
            request_exists = codex_request_path(selected_draft).exists()
            if request_exists:
                st.info("这个草稿已请求 Codex 校正。校正完成后，这里会自动出现可预览和导入的数据。")
            else:
                st.info("这个草稿还没有发送校正请求。点击下方按钮后，Codex 自动任务会接手处理。")
            if st.button(
                "请求 Codex 校正",
                key=f"request_codex_review_{selected_draft.name}",
                icon=":material/auto_fix_high:",
                use_container_width=True,
            ):
                request_file = mark_manual_position_draft_for_codex(selected_draft)
                st.success("已请求 Codex 校正。")
                st.caption(f"请求标记：{request_file}")
    else:
        st.info("还没有截图草稿。")

    preview_ready = bool(rows) and selected_draft is not None
    with import_col:
        if st.button(
            "导入校正草稿",
            key="import_manual_positions",
            type="primary",
            icon=":material/check_circle:",
            use_container_width=True,
            disabled=not preview_ready,
        ):
            try:
                with st.spinner("正在写入持仓..."):
                    import_source_label = str(draft_payload.get("source_label") or source_label)
                    if import_source_label not in MANUAL_POSITION_SOURCES:
                        import_source_label = source_label
                    file_names = [
                        str(item.get("original_name") or Path(str(item.get("saved_path") or "")).name)
                        for item in draft_payload.get("files", [])
                        if isinstance(item, dict)
                    ]
                    message = import_manual_positions_via_dashboard(
                        import_source_label,
                        rows,
                        settings,
                        file_names=file_names,
                    )
                if selected_draft is not None:
                    shutil.rmtree(selected_draft, ignore_errors=True)
                load_data.clear()
                push_flash("success", f"{message} 已清理草稿目录。")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if preview_ready:
        st.caption(f"当前预览草稿：{selected_draft}")
        st.dataframe(preview_rows_frame(rows), use_container_width=True, hide_index=True)


def fund_codes_from_positions(positions: pd.DataFrame) -> list[str]:
    if positions.empty or "asset_type" not in positions.columns:
        return []
    fund_rows = positions[positions["asset_type"] == "fund"]
    return sorted(
        {
            normalize_fund_code(str(symbol))
            for symbol in fund_rows.get("symbol", pd.Series(dtype=str)).dropna().tolist()
            if normalize_fund_code(str(symbol))
        }
    )


def fund_refresh_gap_from_positions(positions: pd.DataFrame) -> tuple[int, list[str]]:
    if positions.empty or "asset_type" not in positions.columns:
        return 0, []
    fund_rows = positions[positions["asset_type"] == "fund"]
    missing_rows = fund_rows[
        ~fund_rows.get("symbol", pd.Series(dtype=str)).fillna("").astype(str).apply(lambda item: bool(normalize_fund_code(item)))
    ]
    names = []
    for name in missing_rows.get("instrument_name", pd.Series(dtype=str)).fillna("").astype(str):
        if name and name not in names:
            names.append(name)
    return int(len(missing_rows.index)), names[:8]


def refresh_fund_navs_via_dashboard(positions: pd.DataFrame, settings: Settings) -> str:
    codes = fund_codes_from_positions(positions)
    if not codes:
        return "没有找到可刷新净值的基金代码。"
    provider = EastmoneyFundNavProvider(settings=settings)
    navs = list(provider.fetch_many(codes).values())
    client = get_supabase(use_service_role=True, settings=settings)
    loaded = upsert_fund_navs(client, navs)
    updated = update_fund_positions_from_dashboard(client, navs)
    ok_count = sum(1 for nav in navs if nav.status == "ok")
    return f"基金净值刷新完成：成功 {ok_count}/{len(codes)} 个，写入 {loaded} 条净值，更新 {updated} 条基金持仓。"


def us_stock_symbols_from_positions(positions: pd.DataFrame) -> list[str]:
    if positions.empty:
        return []
    if not {"asset_type", "currency", "symbol"}.issubset(set(positions.columns)):
        return []
    quote_mask = positions["currency"].astype(str).str.upper().eq("USD") & positions["asset_type"].isin(["stock", "fund"])
    if "provider" in positions.columns:
        quote_mask &= positions["provider"].astype(str).str.upper().eq("IBKR")
    quote_rows = positions[quote_mask]
    symbols = []
    for symbol in quote_rows["symbol"].dropna().astype(str):
        normalized = normalize_us_symbol(symbol)
        if normalized and not normalized.isdigit():
            symbols.append(normalized)
    return sorted(set(symbols))


def gold_positions_count(positions: pd.DataFrame) -> int:
    if positions.empty or "asset_type" not in positions.columns:
        return 0
    return int((positions["asset_type"] == "gold").sum())


def cny_to_usd_rate_from_client(client: Any) -> FxRate | None:
    rows = client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []
    rate = latest_rate_from_rows("CNY", rows)
    if rate is not None:
        return rate
    try:
        return fetch_online_usd_rates().get("CNY")
    except Exception:
        return None


def update_fund_positions_from_dashboard(client: Any, navs: list[FundNav]) -> int:
    nav_map = {nav.fund_code: nav for nav in navs if nav.status == "ok" and nav.unit_nav > 0}
    if not nav_map:
        return 0

    fx_rows = client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []
    updated = 0
    positions = (
        client.table("positions_current")
        .select("id,quantity,currency,cost_original,market_value_original,quantity_source,instruments(symbol,asset_type)")
        .eq("currency", "CNY")
        .execute()
        .data
        or []
    )
    cny_rate = latest_rate_from_rows("CNY", fx_rows)
    for position in positions:
        instrument = position.get("instruments") or {}
        if str(instrument.get("asset_type") or "") != "fund":
            continue
        fund_code = normalize_fund_code(str(instrument.get("symbol") or ""))
        nav = nav_map.get(fund_code)
        if nav is None:
            continue
        quantity = Decimal(str(position.get("quantity") or "0"))
        if quantity <= 0:
            continue
        existing_value = Decimal(str(position.get("market_value_original") or "0"))
        quantity_source = str(position.get("quantity_source") or "")
        inferred_quantity = False
        if existing_value > 0 and (quantity == 1 or quantity_source == "manual"):
            quantity = (existing_value / nav.unit_nav).quantize(Decimal("0.000001"))
            inferred_quantity = True
        market_value = (quantity * nav.unit_nav).quantize(Decimal("0.01"))
        payload: dict[str, Any] = {
            "quantity": str(quantity),
            "price_original": str(nav.unit_nav),
            "market_value_original": str(market_value),
            "market_value_usd": str(convert_to_usd(market_value, "CNY", cny_rate)) if cny_rate else None,
            "fx_rate_to_usd": str(cny_rate.rate) if cny_rate else None,
            "fx_rate_source": f"fund_nav:{nav.source}",
            "fx_rate_date": nav.nav_date.isoformat(),
        }
        if inferred_quantity:
            payload["quantity_source"] = "inferred"
            payload["estimate_note"] = f"Quantity inferred from existing market value and {nav.nav_date.isoformat()} fund NAV."
        cost = position.get("cost_original")
        if cost is not None:
            pnl = (market_value - Decimal(str(cost))).quantize(Decimal("0.01"))
            payload["unrealized_pnl_original"] = str(pnl)
            payload["total_pnl_original"] = str(pnl)
            if Decimal(str(cost)) != 0:
                payload["pnl_pct"] = str((pnl / Decimal(str(cost))).quantize(Decimal("0.000001")))
        client.table("positions_current").update(payload).eq("id", position["id"]).execute()
        updated += 1
    return updated


def update_position_market_quotes_from_dashboard(client: Any, quotes: dict[str, MarketQuote]) -> int:
    if not quotes:
        return 0

    fx_rows = client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []
    updated = 0
    for symbol, quote in quotes.items():
        positions = (
            client.table("positions_current")
            .select("id,quantity,cost_original,instruments(symbol,asset_type)")
            .eq("currency", quote.currency)
            .execute()
            .data
            or []
        )
        for position in positions:
            instrument = position.get("instruments") or {}
            is_gold_quote = symbol == "GOLD-CNY-G"
            is_gold_position = str(instrument.get("asset_type") or "") == "gold"
            symbol_matches = str(instrument.get("symbol") or "").upper() == symbol
            if not ((is_gold_quote and is_gold_position) or symbol_matches):
                continue

            quantity = Decimal(str(position.get("quantity") or "0"))
            market_value = (quantity * quote.price).quantize(Decimal("0.01"))
            fx_rate = latest_rate_from_rows(quote.currency, fx_rows)
            if quote.currency == "USD":
                fx_rate = FxRate("USD", "USD", Decimal("1"), quote.as_of.date(), quote.source)
            market_value_usd = convert_to_usd(market_value, quote.currency, fx_rate)
            payload: dict[str, Any] = {
                "price_original": str(quote.price),
                "market_value_original": str(market_value),
                "market_value_usd": str(market_value_usd) if market_value_usd is not None else None,
                "fx_rate_to_usd": str(fx_rate.rate) if fx_rate else None,
                "fx_rate_source": quote.source,
                "fx_rate_date": quote.as_of.date().isoformat(),
            }
            cost = position.get("cost_original")
            if cost is not None:
                pnl = (market_value - Decimal(str(cost))).quantize(Decimal("0.01"))
                payload["unrealized_pnl_original"] = str(pnl)
                payload["total_pnl_original"] = str(pnl)
                if Decimal(str(cost)) != 0:
                    payload["pnl_pct"] = str((pnl / Decimal(str(cost))).quantize(Decimal("0.000001")))
            client.table("positions_current").update(
                payload
            ).eq("id", position["id"]).execute()
            updated += 1
    return updated


def refresh_us_stock_quotes_via_dashboard(positions: pd.DataFrame, settings: Settings) -> str:
    symbols = us_stock_symbols_from_positions(positions)
    if not symbols:
        return "没有找到可刷新行情的美元股票或 ETF。"
    provider = YahooMarketQuoteProvider()
    quotes = provider.fetch_many(symbols)
    if not quotes:
        error_preview = "；".join(provider.errors[:3])
        detail = f"（{error_preview}）" if error_preview else ""
        return f"暂时没有获取到美股行情{detail}，可能是 Yahoo 行情源限流或网络不稳定，请稍后再试。"
    client = get_supabase(use_service_role=True, settings=settings)
    updated = update_position_market_quotes_from_dashboard(client, quotes)
    failed_count = len(symbols) - len(quotes)
    suffix = f"，{failed_count} 个暂未取到" if failed_count else ""
    return f"美股行情刷新完成：获取 {len(quotes)}/{len(symbols)} 个报价，更新 {updated} 条持仓{suffix}。"


def fetch_gold_cny_per_gram_quote(usd_cny_rate: Decimal) -> tuple[MarketQuote | None, list[str]]:
    provider = YahooMarketQuoteProvider()
    try:
        ounce_quote = provider.fetch_one("GC=F")
    except Exception as exc:
        return None, [f"GC=F: {exc}"]
    if ounce_quote is None or ounce_quote.price <= 0 or usd_cny_rate <= 0:
        return None, provider.errors
    troy_ounce_grams = Decimal("31.1034768")
    price = (ounce_quote.price * usd_cny_rate / troy_ounce_grams).quantize(Decimal("0.000001"))
    return (
        MarketQuote(
            symbol="GOLD-CNY-G",
            price=price,
            currency="CNY",
            as_of=ounce_quote.as_of,
            source=f"{ounce_quote.source}:GC=F:usd_cny",
        ),
        provider.errors,
    )


def refresh_gold_quotes_via_dashboard(positions: pd.DataFrame, settings: Settings) -> str:
    count = gold_positions_count(positions)
    if not count:
        return "没有找到可刷新的黄金持仓。"
    client = get_supabase(use_service_role=True, settings=settings)
    cny_rate = cny_to_usd_rate_from_client(client)
    if cny_rate is None or cny_rate.rate <= 0:
        return "暂时没有可用的人民币汇率，无法把黄金美元报价换算成人民币/克。"
    usd_cny_rate = (Decimal("1") / cny_rate.rate)
    quote, errors = fetch_gold_cny_per_gram_quote(usd_cny_rate)
    if quote is None:
        detail = f"（{';'.join(errors[:3])}）" if errors else ""
        return f"暂时没有获取到黄金行情{detail}，请稍后再试。"
    updated = update_position_market_quotes_from_dashboard(client, {quote.symbol: quote})
    return f"黄金行情刷新完成：最新约 {quote.price} 元/克，更新 {updated}/{count} 条黄金持仓。"


def render_market_refresh_panel(positions: pd.DataFrame, settings: Settings, usd_cny_snapshot: dict[str, str] | None) -> None:
    fund_codes = fund_codes_from_positions(positions)
    missing_fund_code_count, missing_fund_code_names = fund_refresh_gap_from_positions(positions)
    stock_symbols = us_stock_symbols_from_positions(positions)
    gold_count = gold_positions_count(positions)
    disabled = not can_write_from_dashboard(settings)
    st.markdown("<div class='section-title'>行情刷新</div>", unsafe_allow_html=True)
    caption = "基金/QDII 使用最新披露净值；美股使用当前可取到的市场报价；黄金按黄金报价换算为人民币/克。刷新会写入当前持仓价格、市值和盈亏。"
    if usd_cny_snapshot:
        caption += f" 当前汇率：{usd_cny_snapshot['value']}。"
    if missing_fund_code_count:
        preview_names = "、".join(missing_fund_code_names[:3])
        caption += f" 另有 {missing_fund_code_count} 条基金/QDII持仓缺少 6 位基金代码，暂不参与净值刷新"
        if preview_names:
            caption += f"：{preview_names}"
        caption += "。"
    st.caption(caption)
    col_fund, col_stock, col_gold = st.columns(3)
    with col_fund:
        if st.button(
            f"刷新基金和QDII净值（{len(fund_codes)}个代码）",
            key="hero_refresh_fund_navs",
            icon=":material/update:",
            use_container_width=True,
            disabled=disabled or not fund_codes,
        ):
            try:
                with st.spinner("正在刷新基金/QDII 净值..."):
                    message = refresh_fund_navs_via_dashboard(positions, settings)
                load_data.clear()
                push_flash("success", message)
                st.rerun()
            except MissingFundNavTable as exc:
                st.error(str(exc))
                st.code((ROOT / "sql" / "20260513_fund_navs.sql").read_text(encoding="utf-8"), language="sql")
            except Exception as exc:
                st.error(str(exc))
    with col_stock:
        if st.button(
            f"刷新美股实时行情（{len(stock_symbols)}个）",
            key="hero_refresh_us_quotes",
            icon=":material/monitoring:",
            use_container_width=True,
            disabled=disabled or not stock_symbols,
        ):
            try:
                with st.spinner("正在刷新美股行情..."):
                    message = refresh_us_stock_quotes_via_dashboard(positions, settings)
                load_data.clear()
                push_flash("success", message)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    with col_gold:
        if st.button(
            f"刷新黄金行情（{gold_count}条）",
            key="hero_refresh_gold_quotes",
            icon=":material/diamond:",
            use_container_width=True,
            disabled=disabled or not gold_count,
        ):
            try:
                with st.spinner("正在刷新黄金行情..."):
                    message = refresh_gold_quotes_via_dashboard(positions, settings)
                load_data.clear()
                push_flash("success", message)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if disabled:
        st.info("当前环境没有写入权限。配置 SUPABASE_SERVICE_ROLE_KEY 后可以启用行情刷新。")


def render_operations_panel(imports: pd.DataFrame, errors: pd.DataFrame, positions: pd.DataFrame | None = None) -> None:
    settings = get_settings()
    st.markdown("<div class='section-title'>操作台</div>", unsafe_allow_html=True)

    if not can_write_from_dashboard(settings):
        st.info("当前环境只有只读权限。要启用这里的按钮，请在当前 Streamlit 环境中配置 SUPABASE_SERVICE_ROLE_KEY。")
        render_import_status(imports, errors)
        return

    left, right = st.columns(2)
    with left:
        st.markdown(
            """
            <div class="ops-card">
                <div class="ops-topline ops-local"></div>
                <div class="ops-tag ops-tag-local">本机操作</div>
                <div class="ops-title">IBKR 同步</div>
                <div class="muted-copy">适合你在电脑上打开看板时使用。先登录本机的 IB Gateway/TWS，再点击同步。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        account = st.text_input("同步账户", value="all", key="ibkr_sync_account")
        local_ready = st.toggle("我已在本机打开并登录 Gateway / TWS", value=False, key="ibkr_local_ready", width="stretch")
        if st.button(
            "同步 IBKR",
            key="sync_ibkr_button",
            type="primary",
            icon=":material/sync:",
            use_container_width=True,
            disabled=not local_ready,
        ):
            try:
                with st.spinner("正在同步 IBKR..."):
                    message = sync_ibkr_via_dashboard(account.strip() or "all", settings)
                load_data.clear()
                push_flash("success", message)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with right:
        st.markdown(
            """
            <div class="ops-card">
                <div class="ops-topline ops-cloud"></div>
                <div class="ops-tag ops-tag-cloud">云端上传</div>
                <div class="ops-title">汇丰 PDF 上传</div>
                <div class="muted-copy">这个入口支持手机使用。你可以直接从 iCloud 选择 PDF 上传，预检后再决定是否写入数据库。</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        uploaded_pdf = st.file_uploader("上传最新汇丰 PDF", type=["pdf"], key="hsbc_pdf_uploader")
        dry_run = st.toggle("先预检，不写数据库", value=False, key="hsbc_pdf_dry_run", width="stretch")
        button_label = "预检汇丰 PDF" if dry_run else "导入汇丰 PDF"
        if st.button(
            button_label,
            key="import_hsbc_button",
            icon=":material/upload_file:",
            use_container_width=True,
            disabled=uploaded_pdf is None,
        ):
            try:
                with st.spinner("正在解析 PDF..."):
                    message, preview = import_hsbc_pdf_via_dashboard(
                        uploaded_pdf.name,
                        uploaded_pdf.getvalue(),
                        settings,
                        dry_run=dry_run,
                    )
                st.session_state[HSBC_PREVIEW_KEY] = preview
                st.session_state[HSBC_PREVIEW_NAME_KEY] = uploaded_pdf.name
                if dry_run:
                    st.success(message)
                else:
                    load_data.clear()
                    push_flash("success", message)
                    st.rerun()
            except Exception as exc:
                st.error(str(exc))

        render_hsbc_preview()

    render_manual_positions_import(settings)
    render_import_status(imports, errors)
    render_command_hint()


def render_command_hint() -> None:
    with st.expander("命令行入口", expanded=False):
        st.code(
            "python scripts/load_fx_rates.py sample_data/fx_rates.csv\n"
            "python scripts/load_fund_navs.py --fund-code 270023\n"
            "python scripts/import_hsbc_pdf.py HSBC/资产配置报告.pdf\n"
            "python scripts/sync_ibkr.py --account all",
            language="powershell",
        )


def render_overview(df: pd.DataFrame, display_currency: str) -> None:
    render_metrics(df, display_currency)
    render_spotlight_panels(df, display_currency)


def render_structure(df: pd.DataFrame, display_currency: str) -> None:
    render_allocation(df, display_currency)
    render_summary_tables(df, display_currency)


def main() -> None:
    inject_styles()
    if not require_password():
        return

    try:
        positions, imports, errors, fx_rates, fund_navs, using_supabase = load_data()
    except MissingSupabaseConfig as exc:
        st.error(str(exc))
        st.stop()

    if not using_supabase:
        st.warning("当前是演示模式，页面展示的是仓库自带的 demo 样例数据，不是你的真实持仓。配置 Supabase 后会自动读取你的云端资产数据。")

    positions, fx_note, rate_map = apply_fx_fallback(positions, fx_rates)
    positions = apply_fund_nav_estimates(positions, fund_navs, rate_map)
    positions = add_pnl_columns(positions)
    st.session_state["usd_cny_snapshot"] = get_usd_cny_snapshot(rate_map)
    settings = get_settings()

    render_flash()
    render_hero(positions, demo_mode=not using_supabase)
    render_market_refresh_panel(positions, settings, st.session_state.get("usd_cny_snapshot"))

    if positions.empty:
        render_operations_panel(imports, errors, positions)
        st.info("还没有持仓数据。")
        st.stop()

    display_currency, section = render_sidebar_controls(positions)
    positions = add_display_columns(positions, display_currency, rate_map)

    if section == "总览":
        render_overview(positions, display_currency)
    elif section == "结构":
        render_structure(positions, display_currency)
    elif section == "持仓":
        render_holdings(positions, display_currency)
    else:
        render_operations_panel(imports, errors, positions)


if __name__ == "__main__":
    main()
