from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from portfolio_mvp.config import get_settings
from portfolio_mvp.db import MissingSupabaseConfig, fetch_dashboard_data, get_supabase
from portfolio_mvp.fx import fetch_online_usd_rates, latest_rate_from_rows


ASSET_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "wealth_product": "理财",
    "gold": "黄金",
    "cash": "现金",
    "crypto": "加密货币",
    "bond": "债券",
    "other": "其他",
}


st.set_page_config(page_title="个人资产管理 MVP", layout="wide")


def require_password() -> bool:
    settings = get_settings()
    if not settings.streamlit_password:
        return True
    if st.session_state.get("authenticated"):
        return True
    with st.form("login"):
        st.subheader("个人资产管理")
        password = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("进入")
    if submitted and password == settings.streamlit_password:
        st.session_state["authenticated"] = True
        st.rerun()
    elif submitted:
        st.error("密码不正确")
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
    accounts = df["accounts"].apply(lambda x: x if isinstance(x, dict) else {})
    instruments = df["instruments"].apply(lambda x: x if isinstance(x, dict) else {})
    df = df.copy()
    df["provider"] = accounts.apply(lambda x: x.get("provider", ""))
    df["account_name"] = accounts.apply(lambda x: x.get("account_name", ""))
    df["symbol"] = instruments.apply(lambda x: x.get("symbol", ""))
    df["instrument_name"] = instruments.apply(lambda x: x.get("name", ""))
    df["isin"] = instruments.apply(lambda x: x.get("isin", ""))
    df["asset_type"] = instruments.apply(lambda x: x.get("asset_type", "other"))
    return coerce_position_columns(df)


def coerce_position_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in ("quantity", "price_original", "market_value_original", "market_value_usd"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    if "valuation_date" in df.columns:
        df["valuation_date"] = pd.to_datetime(df["valuation_date"], errors="coerce").dt.date
    for column in ("provider", "account_name", "symbol", "instrument_name", "asset_type", "currency"):
        if column not in df.columns:
            df[column] = ""
    return df


def empty_positions() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "provider",
            "account_name",
            "symbol",
            "instrument_name",
            "asset_type",
            "quantity",
            "market_value_original",
            "currency",
            "market_value_usd",
            "valuation_date",
        ]
    )


def load_sample_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, bool]:
    sample_path = ROOT / "sample_data" / "positions_demo.csv"
    if sample_path.exists():
        df = pd.read_csv(sample_path)
        df = coerce_position_columns(df)
    else:
        df = empty_positions()
    imports = pd.DataFrame([{"source": "demo", "source_type": "csv", "status": "local_sample", "rows_imported": len(df)}])
    errors = pd.DataFrame()
    fx_rates = pd.DataFrame([{"base_currency": "CNY", "quote_currency": "USD", "rate": 0.138, "rate_date": str(date.today()), "source": "sample"}])
    return df, imports, errors, fx_rates, False


def apply_fx_fallback(df: pd.DataFrame, fx_rates: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    df = df.copy()
    missing = df[(df["market_value_usd"].isna()) | (df["market_value_usd"] == 0)]
    currencies = sorted(set(missing["currency"].dropna().astype(str).str.upper()) - {"USD"})
    source_note = "使用已入库 USD 估值"
    online_rates = {}
    if currencies:
        try:
            online_rates = fetch_online_usd_rates()
            source_note = "使用在线汇率 API"
        except Exception:
            source_note = "在线汇率不可用，使用手动输入"
            st.warning("在线汇率暂时不可用，请手动输入汇率。")

    fx_rows = fx_rates.to_dict("records") if not fx_rates.empty else []
    for currency in currencies:
        rate = online_rates.get(currency)
        if rate is None:
            cached = latest_rate_from_rows(currency, fx_rows)
            if cached:
                rate = cached
        if rate is None:
            default_value = 0.138 if currency == "CNY" else 1.0
            manual = st.number_input(f"{currency} → USD 汇率", min_value=0.0, value=float(default_value), format="%.6f")
            rate_value = Decimal(str(manual))
        else:
            rate_value = rate.rate
        mask = (df["currency"].str.upper() == currency) & ((df["market_value_usd"].isna()) | (df["market_value_usd"] == 0))
        df.loc[mask, "market_value_usd"] = df.loc[mask, "market_value_original"] * float(rate_value)
    df.loc[df["currency"].str.upper() == "USD", "market_value_usd"] = df.loc[df["currency"].str.upper() == "USD", "market_value_original"]
    return df, source_note


def render_metrics(df: pd.DataFrame) -> None:
    total_usd = df["market_value_usd"].sum()
    ibkr_usd = df[df["provider"].str.upper() == "IBKR"]["market_value_original"].sum()
    cny_total = df[df["currency"].str.upper() == "CNY"]["market_value_original"].sum()
    accounts = df[["provider", "account_name"]].drop_duplicates().shape[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总资产 USD", f"${total_usd:,.2f}")
    c2.metric("IBKR USD 资产", f"${ibkr_usd:,.2f}")
    c3.metric("人民币资产", f"¥{cny_total:,.2f}")
    c4.metric("账户数量", str(accounts))


def render_asset_pie(df: pd.DataFrame) -> None:
    grouped = df.groupby("asset_type", as_index=False)["market_value_usd"].sum()
    grouped = grouped[grouped["market_value_usd"] > 0]
    grouped["资产类型"] = grouped["asset_type"].map(ASSET_LABELS).fillna("其他")
    if grouped.empty:
        st.info("还没有可用于绘制饼图的持仓数据。")
        return
    fig = px.pie(grouped, values="market_value_usd", names="资产类型", hole=0.35)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=380, legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)


def render_positions_table(df: pd.DataFrame) -> None:
    st.subheader("持仓明细")
    choices = ["全部"] + [ASSET_LABELS.get(x, x) for x in sorted(df["asset_type"].dropna().unique())]
    reverse_labels = {v: k for k, v in ASSET_LABELS.items()}
    selected = st.selectbox("资产类型", choices)
    page_size = st.selectbox("每页数量", [10, 20, 50], index=0)
    filtered = df.copy()
    if selected != "全部":
        filtered = filtered[filtered["asset_type"] == reverse_labels.get(selected, selected)]
    total_rows = len(filtered)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page = st.number_input("页码", min_value=1, max_value=total_pages, value=1, step=1)
    start = (page - 1) * page_size
    page_df = filtered.iloc[start : start + page_size].copy()
    total_usd = df["market_value_usd"].sum() or 1
    page_df["占总资产"] = page_df["market_value_usd"] / total_usd
    view = page_df[
        [
            "provider",
            "account_name",
            "asset_type",
            "symbol",
            "instrument_name",
            "quantity",
            "market_value_original",
            "currency",
            "market_value_usd",
            "占总资产",
            "valuation_date",
        ]
    ].rename(
        columns={
            "provider": "机构",
            "account_name": "账户",
            "asset_type": "资产类型",
            "symbol": "代码",
            "instrument_name": "名称",
            "quantity": "数量",
            "market_value_original": "原币种市值",
            "currency": "币种",
            "market_value_usd": "USD 市值",
            "valuation_date": "估值日期",
        }
    )
    view["资产类型"] = view["资产类型"].map(ASSET_LABELS).fillna("其他")
    st.caption(f"第 {page} / {total_pages} 页，共 {total_rows} 条")
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "原币种市值": st.column_config.NumberColumn(format="%.2f"),
            "USD 市值": st.column_config.NumberColumn(format="$%.2f"),
            "占总资产": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=1),
        },
    )


def render_upload_hint() -> None:
    with st.expander("上传与同步入口"):
        st.write("CSV/PDF 文件请先通过本地脚本导入 Supabase。Streamlit 第一版只作为查看入口，避免把 service role key 暴露在网页端。")
        st.code(
            "python scripts/load_fx_rates.py sample_data/fx_rates.csv\n"
            "python scripts/import_csv.py sample_data/transactions_template.csv\n"
            "python scripts/import_hsbc_pdf.py path/to/hsbc_cn_statement.pdf\n"
            "python scripts/sync_ibkr.py --account all",
            language="bash",
        )


if require_password():
    st.title("个人资产管理 MVP")
    try:
        positions, imports, errors, fx_rates, using_supabase = load_data()
    except MissingSupabaseConfig as exc:
        st.error(str(exc))
        st.stop()

    if not using_supabase:
        st.info("当前使用本地样例数据。配置 Supabase 后会自动读取云端数据库。")
    positions, fx_note = apply_fx_fallback(positions, fx_rates)
    st.caption(f"汇率状态：{fx_note}")

    render_metrics(positions)
    left, right = st.columns([1, 1])
    with left:
        st.subheader("资产类型占比")
        render_asset_pie(positions)
    with right:
        st.subheader("按账户与币种")
        if positions.empty:
            st.info("暂无数据")
        else:
            account_summary = positions.groupby(["provider", "account_name", "currency"], as_index=False)[
                ["market_value_original", "market_value_usd"]
            ].sum()
            st.dataframe(account_summary, use_container_width=True, hide_index=True)

    render_positions_table(positions)
    render_upload_hint()

    with st.expander("最近导入记录"):
        st.dataframe(imports, use_container_width=True, hide_index=True)
    with st.expander("待处理错误"):
        if errors.empty:
            st.success("暂无导入错误。")
        else:
            st.dataframe(errors, use_container_width=True, hide_index=True)
