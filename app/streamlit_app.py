from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portfolio_mvp.config import get_settings
from portfolio_mvp.db import MissingSupabaseConfig, fetch_dashboard_data, get_supabase
from portfolio_mvp.fx import FxRate, fetch_online_usd_rates, latest_rate_from_rows


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

DISPLAY_CURRENCY_LABELS = {
    "USD": "美元",
    "CNY": "人民币",
}

ASSET_ORDER = ["stock", "fund", "wealth_product", "bond", "cash", "gold", "crypto", "other"]
CURRENCY_ALIASES = {"CNH": "CNY"}
PANEL_SPECS = [
    {
        "asset_type": "stock",
        "title": "股票",
        "subtitle": "股票与 ETF 持仓，不含“其他”分类",
        "accent": "#3B82F6",
    },
    {
        "asset_type": "bond",
        "title": "美债",
        "subtitle": "债券持仓总览与单券分布",
        "accent": "#22C55E",
    },
    {
        "asset_type": "fund",
        "title": "基金",
        "subtitle": "基金产品规模与持仓结构",
        "accent": "#A855F7",
    },
    {
        "asset_type": "wealth_product",
        "title": "理财",
        "subtitle": "理财产品总额与明细结构",
        "accent": "#F59E0B",
    },
]


st.set_page_config(page_title="LXY的Finsight", layout="wide")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, #ffffff 0%, #f7f9fc 100%);
            border: 1px solid #e7edf5;
            border-radius: 12px;
            padding: 0.75rem 0.9rem;
        }
        .spotlight-title {
            font-size: 1.02rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 0.1rem;
        }
        .spotlight-subtitle {
            color: #64748b;
            font-size: 0.82rem;
            margin-bottom: 0.5rem;
        }
        .spotlight-chip {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            background: #f1f5f9;
            color: #475569;
            font-size: 0.78rem;
            font-weight: 600;
            margin-right: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def require_password() -> bool:
    settings = get_settings()
    if not settings.streamlit_password:
        return True
    if st.session_state.get("authenticated"):
        return True
    with st.form("login"):
        st.subheader("LXY的Finsight")
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("进入")
    if submitted and password == settings.streamlit_password:
        st.session_state["authenticated"] = True
        st.rerun()
    elif submitted:
        st.error("密码不正确。")
    return False


@st.cache_data(ttl=60)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    settings = get_settings()
    if settings.has_supabase_read_config:
        client = get_supabase(use_service_role=False, settings=settings)
        data = fetch_dashboard_data(client)
        return (
            normalize_positions(pd.DataFrame(data["positions"])),
            pd.DataFrame(data["imports"]),
            pd.DataFrame(data["errors"]),
            pd.DataFrame(data["fx_rates"]),
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
    ):
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str)
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
        ]
    )


def load_sample_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    sample_path = ROOT / "sample_data" / "positions_demo.csv"
    df = normalize_positions(pd.read_csv(sample_path)) if sample_path.exists() else empty_positions()
    imports = pd.DataFrame(
        [{"source": "demo", "source_type": "csv", "status": "local_sample", "rows_imported": len(df)}]
    )
    errors = pd.DataFrame()
    fx_rates = pd.DataFrame(
        [
            {"base_currency": "CNY", "quote_currency": "USD", "rate": 0.138, "rate_date": str(date.today()), "source": "sample"},
            {"base_currency": "HKD", "quote_currency": "USD", "rate": 0.128, "rate_date": str(date.today()), "source": "sample"},
        ]
    )
    return df, imports, errors, fx_rates, False


def canonical_currency(value: str) -> str:
    currency = (value or "").strip().upper()
    return CURRENCY_ALIASES.get(currency, currency)


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


def render_toolbar(df: pd.DataFrame) -> str:
    latest_date = latest_valuation_date(df)
    c1, c2 = st.columns([1, 5])
    display_currency = c1.selectbox(
        "显示币种",
        options=["USD", "CNY"],
        format_func=lambda code: f"{DISPLAY_CURRENCY_LABELS[code]} ({code})",
    )
    c2.caption(f"当前按每个账户的最新快照统计。最新估值日期：{latest_date or '暂无'}")
    return display_currency


def render_metrics(df: pd.DataFrame, display_currency: str) -> None:
    total_value = df["display_value"].sum(skipna=True)
    total_pnl = df["display_pnl"].sum(skipna=True)
    ibkr_total = df[df["provider"] == "IBKR"]["display_value"].sum(skipna=True)
    hsbc_total = df[df["provider"] == "HSBC China"]["display_value"].sum(skipna=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"总资产 {display_currency}", money(total_value, display_currency))
    c2.metric(f"已识别盈亏 {display_currency}", money(total_pnl, display_currency))
    c3.metric("IBKR", money(ibkr_total, display_currency))
    c4.metric("HSBC China", money(hsbc_total, display_currency))


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
        marker=dict(color=accent, line=dict(color=accent, width=1), opacity=0.9),
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
        height=300,
        margin=dict(l=10, r=36, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    fig.update_xaxes(
        title=None,
        tickprefix=currency_symbol(display_currency),
        showgrid=True,
        gridcolor="rgba(148,163,184,0.22)",
        zeroline=False,
    )
    fig.update_yaxes(title=None, showgrid=False)
    return fig


def render_spotlight_panel(df: pd.DataFrame, spec: dict[str, str], display_currency: str) -> None:
    grouped = aggregate_spotlight_positions(df, spec["asset_type"])
    total_value = grouped["display_value"].sum(skipna=True)
    total_pnl = grouped["display_pnl"].sum(skipna=True)
    total_cost = grouped["display_cost"].sum(skipna=True)
    total_pct = total_pnl / total_cost if total_cost else None

    with st.container(border=True):
        st.markdown(
            (
                f"<div class='spotlight-title'>{spec['title']}</div>"
                f"<div class='spotlight-subtitle'>{spec['subtitle']}</div>"
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            (
                f"<span class='spotlight-chip'>持仓 {len(grouped)} 项</span>"
                f"<span class='spotlight-chip'>统计币种 {display_currency}</span>"
            ),
            unsafe_allow_html=True,
        )
        pnl_available = grouped["display_pnl"].notna().any()
        cost_available = grouped["display_cost"].notna().any()
        total_pnl_display = total_pnl if pnl_available else None
        total_pct_display = total_pct if pnl_available and cost_available else None
        m1, m2, m3 = st.columns(3)
        m1.metric("总资金", money(total_value, display_currency))
        m2.metric("盈亏额", metric_money(total_pnl_display, display_currency))
        m3.metric("盈亏率", percent_text(total_pct_display))

        if grouped.empty:
            st.info(f"当前还没有可展示的{spec['title']}持仓。")
            return

        fig = build_spotlight_chart(grouped, spec["accent"], display_currency)
        st.plotly_chart(fig, use_container_width=True)


def render_spotlight_panels(df: pd.DataFrame, display_currency: str) -> None:
    st.subheader("专题看板")
    rows = [PANEL_SPECS[:2], PANEL_SPECS[2:]]
    for specs in rows:
        columns = st.columns(2)
        for column, spec in zip(columns, specs):
            with column:
                render_spotlight_panel(df, spec, display_currency)


def render_allocation(df: pd.DataFrame, display_currency: str) -> None:
    left, right = st.columns([1, 1])
    with left:
        st.subheader("资产类别")
        grouped = df.groupby(["asset_type", "asset_label"], as_index=False)["display_value"].sum()
        grouped = grouped[grouped["display_value"] > 0]
        grouped["sort"] = grouped["asset_type"].apply(lambda item: ASSET_ORDER.index(item) if item in ASSET_ORDER else 99)
        grouped = grouped.sort_values("sort")
        if grouped.empty:
            st.info("还没有可展示的持仓。")
        else:
            fig = px.pie(grouped, values="display_value", names="asset_label", hole=0.44)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=360, legend_title_text="")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("机构与币种")
        grouped = df.groupby(["provider", "currency"], as_index=False)["display_value"].sum()
        grouped = grouped[grouped["display_value"] > 0]
        if grouped.empty:
            st.info("还没有可展示的机构和币种数据。")
        else:
            fig = px.bar(grouped, x="provider", y="display_value", color="currency", text_auto=".2s")
            fig.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=360,
                xaxis_title="",
                yaxis_title=display_currency,
            )
            st.plotly_chart(fig, use_container_width=True)


def render_summary_tables(df: pd.DataFrame, display_currency: str) -> None:
    st.subheader("汇总")
    tab1, tab2, tab3 = st.tabs(["按机构", "按币种", "按资产类型"])
    with tab1:
        show_summary(df, ["provider"], {"provider": "机构"}, display_currency)
    with tab2:
        show_summary(df, ["currency"], {"currency": "币种"}, display_currency)
    with tab3:
        show_summary(df, ["asset_label"], {"asset_label": "资产类型"}, display_currency)


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


def render_positions_table(df: pd.DataFrame, display_currency: str) -> None:
    st.subheader("持仓详情")
    providers = ["全部"] + sorted(item for item in df["provider"].dropna().unique() if item)
    assets = ["全部"] + [ASSET_LABELS[key] for key in ASSET_ORDER if key in set(df["asset_type"])]

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    selected_provider = c1.selectbox("机构", providers)
    selected_asset = c2.selectbox("资产类型", assets)
    page_size = c3.selectbox("每页数量", [10, 20, 50], index=1)
    search_text = c4.text_input("搜索代码或名称", value="").strip().lower()

    filtered = df.copy()
    if selected_provider != "全部":
        filtered = filtered[filtered["provider"] == selected_provider]
    if selected_asset != "全部":
        reverse = {label: key for key, label in ASSET_LABELS.items()}
        filtered = filtered[filtered["asset_type"] == reverse.get(selected_asset)]
    if search_text:
        haystack = (
            filtered["symbol"].fillna("").astype(str).str.lower()
            + " "
            + filtered["instrument_name"].fillna("").astype(str).str.lower()
            + " "
            + filtered["display_name"].fillna("").astype(str).str.lower()
        )
        filtered = filtered[haystack.str.contains(search_text, regex=False)]

    filtered = filtered.sort_values(
        by=["display_value", "provider", "account_name", "symbol"],
        ascending=[False, True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    total_rows = len(filtered)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = st.number_input("页码", min_value=1, max_value=total_pages, value=1, step=1)
    page_df = filtered.iloc[(page - 1) * page_size : page * page_size].copy()

    summary_row = {
        "provider": "汇总",
        "account_name": "",
        "asset_label": "",
        "symbol": "",
        "instrument_name": "",
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
    }
    page_df = pd.concat([page_df, pd.DataFrame([summary_row])], ignore_index=True)

    value_column = f"折算市值 {display_currency}"
    pnl_column = f"折算盈亏 {display_currency}"
    view = page_df[
        [
            "provider",
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
        ]
    ].rename(
        columns={
            "provider": "机构",
            "account_name": "账户",
            "asset_label": "资产类型",
            "symbol": "代码",
            "display_name": "名称",
            "quantity": "数量",
            "price_original": "股价",
            "market_value_original": "原币市值",
            "currency": "币种",
            "display_value": value_column,
            "cost_original": "原币成本",
            "display_pnl": pnl_column,
            "pnl_pct": "盈亏率",
            "valuation_date": "估值日期",
        }
    )
    view["盈亏率"] = view["盈亏率"] * 100
    st.caption(f"第 {page} / {total_pages} 页，共 {total_rows} 条。表格末行显示当前筛选结果的汇总。")

    styled_view = style_positions_table(view)
    st.dataframe(
        styled_view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "股价": st.column_config.NumberColumn(format="%.4f"),
            "原币市值": st.column_config.NumberColumn(format="%.2f"),
            value_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            "原币成本": st.column_config.NumberColumn(format="%.2f"),
            pnl_column: st.column_config.NumberColumn(format=number_format(display_currency)),
            "盈亏率": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )


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
    with st.expander("最近导入"):
        st.dataframe(imports, use_container_width=True, hide_index=True)
    with st.expander("待处理问题"):
        if errors.empty:
            st.success("暂无导入错误。")
        else:
            st.dataframe(errors, use_container_width=True, hide_index=True)


def render_upload_hint() -> None:
    with st.expander("导入入口"):
        st.code(
            "python scripts/load_fx_rates.py sample_data/fx_rates.csv\n"
            "python scripts/import_hsbc_pdf.py HSBC/资产配置报告.pdf\n"
            "python scripts/sync_ibkr.py --account all",
            language="powershell",
        )


def main() -> None:
    inject_styles()
    if not require_password():
        return

    st.title("LXY的Finsight")
    st.caption("统一浏览 IBKR 与 HSBC China 的最新持仓、币种结构、资产类别和盈亏情况。")

    try:
        positions, imports, errors, fx_rates, using_supabase = load_data()
    except MissingSupabaseConfig as exc:
        st.error(str(exc))
        st.stop()

    if not using_supabase:
        st.info("当前使用本地样例数据；配置 Supabase 后会自动读取云端数据库。")

    positions, fx_note, rate_map = apply_fx_fallback(positions, fx_rates)
    positions = add_pnl_columns(positions)

    if positions.empty:
        st.info("还没有持仓数据。")
        render_upload_hint()
        st.stop()

    display_currency = render_toolbar(positions)
    positions = add_display_columns(positions, display_currency, rate_map)
    st.caption(f"汇率状态：{fx_note}")

    render_metrics(positions, display_currency)
    render_spotlight_panels(positions, display_currency)
    render_allocation(positions, display_currency)
    render_summary_tables(positions, display_currency)
    render_positions_table(positions, display_currency)
    render_upload_hint()
    render_import_status(imports, errors)


if __name__ == "__main__":
    main()
