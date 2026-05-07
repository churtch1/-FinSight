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
from portfolio_mvp.dashboard import (
    ASSET_LABELS,
    account_summary,
    asset_summary,
    currency_summary,
    dashboard_summary,
    filter_positions,
    load_sample_positions,
    normalize_positions,
    paginate,
    provider_summary,
    top_holdings,
)
from portfolio_mvp.db import MissingSupabaseConfig, fetch_dashboard_data, get_supabase
from portfolio_mvp.fx import fetch_online_usd_rates, latest_rate_from_rows


st.set_page_config(page_title="Portfolio Daily Tracker", page_icon="📊", layout="wide", initial_sidebar_state="expanded")


PALETTE = ["#2f6f5e", "#315a9d", "#b7791f", "#7b5ea7", "#637a3f", "#9a4f64", "#697386"]


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f6f8fb;
            --surface: #ffffff;
            --surface-soft: #f9fbfd;
            --line: #dbe2ea;
            --ink: #17202a;
            --muted: #637083;
            --accent: #2f6f5e;
            --accent-soft: #eaf5f1;
        }
        body { background: var(--bg); }
        .main .block-container {
            max-width: 1240px;
            padding-top: 1rem;
            padding-bottom: 2rem;
        }
        h1, h2, h3, p { letter-spacing: 0; }
        .hero {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: linear-gradient(135deg, #ffffff 0%, #eef7f3 48%, #f5f7ff 100%);
            padding: 1rem 1.1rem;
            margin-bottom: 0.9rem;
        }
        .hero-title {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 1rem;
        }
        .hero-title h1 {
            margin: 0;
            color: var(--ink);
            font-size: 1.75rem;
            line-height: 1.25;
        }
        .hero-title span {
            color: var(--muted);
            font-size: 0.9rem;
            white-space: nowrap;
        }
        .hero-sub {
            color: var(--muted);
            margin-top: 0.45rem;
            line-height: 1.55;
        }
        div[data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 0.8rem 0.9rem;
            min-height: 96px;
        }
        div[data-testid="stMetric"] label {
            color: var(--muted);
            font-size: 0.8rem;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--ink);
            font-size: 1.38rem;
            line-height: 1.2;
        }
        .section-title {
            font-size: 1.02rem;
            font-weight: 700;
            color: var(--ink);
            margin: 0.35rem 0 0.45rem 0;
        }
        .info-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.2rem 0 0.9rem;
        }
        .info-card {
            border: 1px solid var(--line);
            border-radius: 8px;
            background: var(--surface);
            padding: 0.72rem 0.8rem;
        }
        .info-label {
            color: var(--muted);
            font-size: 0.76rem;
            margin-bottom: 0.25rem;
        }
        .info-value {
            color: var(--ink);
            font-size: 0.98rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .health-row {
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
            background: var(--surface-soft);
            color: var(--muted);
            margin: 0.4rem 0 0.9rem;
        }
        @media (max-width: 760px) {
            .main .block-container {
                padding-left: 0.8rem;
                padding-right: 0.8rem;
                padding-top: 0.65rem;
            }
            .hero-title {
                flex-direction: column;
                gap: 0.25rem;
            }
            .hero-title h1 {
                font-size: 1.32rem;
            }
            .hero-title span {
                white-space: normal;
            }
            .info-grid {
                grid-template-columns: 1fr 1fr;
                gap: 0.5rem;
            }
            div[data-testid="stMetric"] {
                min-height: 82px;
                padding: 0.65rem 0.7rem;
            }
            div[data-testid="stMetric"] [data-testid="stMetricValue"] {
                font-size: 1.08rem;
            }
            div[data-testid="stDataFrame"] {
                font-size: 0.82rem;
            }
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
    st.title("Portfolio Daily Tracker")
    with st.form("login"):
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("进入")
    if submitted and password == settings.streamlit_password:
        st.session_state["authenticated"] = True
        st.rerun()
    if submitted:
        st.error("密码不正确")
    return False


@st.cache_data(ttl=60)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    settings = get_settings()
    if settings.has_supabase_read_config:
        try:
            client = get_supabase(use_service_role=False, settings=settings)
            data = fetch_dashboard_data(client)
            return (
                normalize_positions(pd.DataFrame(data["positions"])),
                pd.DataFrame(data["imports"]),
                pd.DataFrame(data["errors"]),
                pd.DataFrame(data["fx_rates"]),
                True,
            )
        except Exception as exc:
            positions, imports, errors, fx_rates, _ = load_sample_data()
            errors = pd.DataFrame([{"error_message": f"Supabase read failed: {exc}"}])
            imports = pd.DataFrame(
                [{"source": "supabase", "source_type": "cloud", "status": "read_failed", "rows_imported": 0, "created_at": str(date.today())}]
            )
            return positions, imports, errors, fx_rates, False
    return load_sample_data()


def load_sample_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    positions = load_sample_positions(ROOT)
    imports = pd.DataFrame(
        [{"source": "demo", "source_type": "csv", "status": "local_sample", "rows_imported": len(positions), "created_at": str(date.today())}]
    )
    errors = pd.DataFrame()
    fx_rates = pd.DataFrame(
        [{"base_currency": "CNY", "quote_currency": "USD", "rate": 0.138, "rate_date": str(date.today()), "source": "sample"}]
    )
    return positions, imports, errors, fx_rates, False


def apply_fx_fallback(df: pd.DataFrame, fx_rates: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if df.empty:
        return df, "暂无持仓"
    df = df.copy()
    missing_mask = (df["market_value_usd"].isna()) | (df["market_value_usd"] == 0)
    currencies = sorted(set(df.loc[missing_mask, "currency"].dropna().astype(str).str.upper()) - {"USD", ""})
    source_note = "使用已入库 USD 估值"
    online_rates = {}
    if currencies:
        try:
            online_rates = fetch_online_usd_rates()
            source_note = "部分估值使用在线汇率补全"
        except Exception:
            source_note = "在线汇率不可用，部分估值使用手动汇率"
    fx_rows = fx_rates.to_dict("records") if not fx_rates.empty else []
    if currencies:
        st.sidebar.markdown("### 汇率补全")
    for currency in currencies:
        rate = online_rates.get(currency) or latest_rate_from_rows(currency, fx_rows)
        if rate is None:
            default_value = 0.138 if currency == "CNY" else 1.0
            manual = st.sidebar.number_input(f"{currency} 到 USD", min_value=0.0, value=float(default_value), format="%.6f")
            rate_value = Decimal(str(manual))
        else:
            rate_value = rate.rate
        mask = (df["currency"] == currency) & missing_mask
        df.loc[mask, "market_value_usd"] = df.loc[mask, "market_value_original"] * float(rate_value)
    usd_mask = df["currency"] == "USD"
    df.loc[usd_mask & missing_mask, "market_value_usd"] = df.loc[usd_mask & missing_mask, "market_value_original"]
    return df, source_note


def render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.title("筛选")
    if df.empty:
        return df
    asset_options = {"all": "全部资产"} | {key: ASSET_LABELS.get(key, key) for key in sorted(df["asset_type"].dropna().unique())}
    provider_options = ["all"] + sorted([value for value in df["provider"].dropna().unique() if value])
    account_options = ["all"] + sorted([value for value in df["account_name"].dropna().unique() if value])
    currency_options = ["all"] + sorted([value for value in df["currency"].dropna().unique() if value])
    selected_asset_label = st.sidebar.selectbox("资产类别", list(asset_options.values()))
    selected_asset = next(key for key, value in asset_options.items() if value == selected_asset_label)
    selected_provider = st.sidebar.selectbox("机构", provider_options, format_func=lambda value: "全部机构" if value == "all" else value)
    selected_account = st.sidebar.selectbox("账户", account_options, format_func=lambda value: "全部账户" if value == "all" else value)
    selected_currency = st.sidebar.selectbox("币种", currency_options, format_func=lambda value: "全部币种" if value == "all" else value)
    query = st.sidebar.text_input("搜索", placeholder="代码、名称、账户")
    min_value = st.sidebar.number_input("最低 USD 市值", min_value=0.0, value=0.0, step=100.0)
    return filter_positions(
        df,
        asset_type=selected_asset,
        provider=selected_provider,
        account_name=selected_account,
        currency=selected_currency,
        query=query,
        min_value=float(min_value),
    )


def render_header(using_supabase: bool, fx_note: str, summary) -> None:
    data_source = "Supabase 云端数据" if using_supabase else "本地示例数据"
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-title">
                <h1>Portfolio Daily Tracker</h1>
                <span>{data_source}</span>
            </div>
            <div class="hero-sub">
                最近估值：{summary.latest_valuation_date} · 最近导入：{summary.latest_import_status} · 汇率：{fx_note}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(summary) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总资产", f"${summary.total_usd:,.2f}")
    c2.metric("持仓数", str(summary.position_count))
    c3.metric("账户数", str(summary.account_count))
    c4.metric("现金占比", f"{summary.cash_ratio:.1f}%")
    c5.metric("最大持仓占比", f"{summary.top_holding_ratio:.1f}%")


def render_health(summary) -> None:
    st.markdown(
        f"""
        <div class="info-grid">
            <div class="info-card"><div class="info-label">最大资产类别</div><div class="info-value">{summary.top_asset_label}</div></div>
            <div class="info-card"><div class="info-label">机构数量</div><div class="info-value">{summary.provider_count}</div></div>
            <div class="info-card"><div class="info-label">复核错误</div><div class="info-value">{summary.error_count}</div></div>
            <div class="info-card"><div class="info-label">集中度提醒</div><div class="info-value">{risk_label(summary.top_holding_ratio)}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_label(top_ratio: float) -> str:
    if top_ratio >= 40:
        return "偏集中"
    if top_ratio >= 25:
        return "中等"
    return "分散"


def plot_donut(data: pd.DataFrame, names: str, values: str, title: str) -> None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("暂无数据")
        return
    fig = px.pie(data, values=values, names=names, hole=0.46, color_discrete_sequence=PALETTE)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=4, r=4, t=4, b=4), height=330, legend_title_text="")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def plot_bar(data: pd.DataFrame, x: str, y: str, title: str, orientation: str = "v") -> None:
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if data.empty:
        st.info("暂无数据")
        return
    if orientation == "h":
        fig = px.bar(data, x=y, y=x, orientation="h", text=y, color=x, color_discrete_sequence=PALETTE)
        fig.update_yaxes(autorange="reversed")
    else:
        fig = px.bar(data, x=x, y=y, text=y, color=x, color_discrete_sequence=PALETTE)
    fig.update_traces(texttemplate="%{text:.2s}", textposition="auto")
    fig.update_layout(
        margin=dict(l=4, r=4, t=4, b=4),
        height=330,
        xaxis_title="",
        yaxis_title="USD",
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_overview(df: pd.DataFrame) -> None:
    left, right = st.columns([1, 1])
    with left:
        plot_donut(asset_summary(df), "asset_label", "market_value_usd", "资产配置")
    with right:
        plot_bar(currency_summary(df), "currency", "market_value_usd", "币种配置")
    left, right = st.columns([1, 1])
    with left:
        plot_bar(provider_summary(df), "provider", "market_value_usd", "机构配置")
    with right:
        top = top_holdings(df, limit=8)
        if not top.empty:
            plot_bar(top, "symbol", "market_value_usd", "Top 持仓", orientation="h")
        else:
            st.info("暂无持仓")


def render_allocation_tables(df: pd.DataFrame) -> None:
    asset_tab, account_tab, currency_tab = st.tabs(["资产类别", "账户", "币种"])
    with asset_tab:
        view = asset_summary(df).rename(columns={"asset_label": "资产类别", "market_value_usd": "USD 估值", "weight": "占比"})
        st.dataframe(view[["资产类别", "USD 估值", "占比"]], width="stretch", hide_index=True)
    with account_tab:
        view = account_summary(df).rename(
            columns={
                "provider": "机构",
                "account_name": "账户",
                "currency": "币种",
                "market_value_original": "原币种金额",
                "market_value_usd": "USD 估值",
                "weight": "占比",
            }
        )
        st.dataframe(view, width="stretch", hide_index=True)
    with currency_tab:
        view = currency_summary(df).rename(columns={"currency": "币种", "market_value_usd": "USD 估值", "weight": "占比"})
        st.dataframe(view, width="stretch", hide_index=True)


def render_positions(df: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">持仓明细</div>', unsafe_allow_html=True)
    if df.empty:
        st.info("暂无持仓数据")
        return
    page_size = st.selectbox("每页数量", [10, 20, 50, 100], index=1)
    page_count = max(1, (len(df) + page_size - 1) // page_size)
    page = st.number_input("页码", min_value=1, max_value=page_count, value=1, step=1)
    page_df, total_pages = paginate(df, int(page), int(page_size))
    total_usd = df["market_value_usd"].sum() or 1
    page_df = page_df.copy()
    page_df["类别"] = page_df["asset_type"].map(ASSET_LABELS).fillna("其他")
    page_df["占比"] = page_df["market_value_usd"] / total_usd * 100
    view = page_df[
        [
            "provider",
            "account_name",
            "类别",
            "symbol",
            "instrument_name",
            "quantity",
            "market_value_original",
            "currency",
            "market_value_usd",
            "占比",
            "valuation_date",
        ]
    ].rename(
        columns={
            "provider": "机构",
            "account_name": "账户",
            "symbol": "代码",
            "instrument_name": "名称",
            "quantity": "数量",
            "market_value_original": "原币种市值",
            "currency": "币种",
            "market_value_usd": "USD 估值",
            "valuation_date": "估值日",
        }
    )
    st.caption(f"第 {int(page)} / {total_pages} 页，共 {len(df)} 条")
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            "数量": st.column_config.NumberColumn(format="%.4f"),
            "原币种市值": st.column_config.NumberColumn(format="%.2f"),
            "USD 估值": st.column_config.NumberColumn(format="$%.2f"),
            "占比": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100),
        },
    )


def render_imports(imports: pd.DataFrame, errors: pd.DataFrame) -> None:
    import_tab, error_tab, help_tab = st.tabs(["最近导入", "复核队列", "同步入口"])
    with import_tab:
        if imports.empty:
            st.info("暂无导入记录")
        else:
            st.dataframe(imports, width="stretch", hide_index=True)
    with error_tab:
        if errors.empty:
            st.success("暂无待处理导入错误")
        else:
            st.dataframe(errors, width="stretch", hide_index=True)
    with help_tab:
        st.write("看板只读取 Supabase；写入仍通过本地脚本完成，避免在网页端暴露 service role key。")
        st.code(
            "py scripts/sync_ibkr.py --account all\n"
            "py scripts/import_pdf.py path/to/statement.pdf\n"
            "py scripts/import_csv.py sample_data/transactions_template.csv",
            language="powershell",
        )


def main() -> None:
    inject_css()
    if not require_password():
        return
    try:
        positions, imports, errors, fx_rates, using_supabase = load_data()
    except MissingSupabaseConfig as exc:
        st.error(str(exc))
        st.stop()
    if get_settings().has_supabase_read_config and not using_supabase:
        st.warning("Supabase 读取暂时不可用，当前显示本地示例数据。请稍后刷新或检查网络/权限。")
    positions, fx_note = apply_fx_fallback(positions, fx_rates)
    filtered = render_sidebar(positions)
    summary = dashboard_summary(filtered, imports, errors)
    render_header(using_supabase, fx_note, summary)
    render_metrics(summary)
    render_health(summary)
    overview_tab, allocation_tab, positions_tab, imports_tab = st.tabs(["总览", "配置分析", "持仓", "导入与复核"])
    with overview_tab:
        render_overview(filtered)
    with allocation_tab:
        render_allocation_tables(filtered)
    with positions_tab:
        render_positions(filtered)
    with imports_tab:
        render_imports(imports, errors)


if __name__ == "__main__":
    main()
