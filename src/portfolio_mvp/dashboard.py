from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ASSET_LABELS: dict[str, str] = {
    "stock": "股票",
    "fund": "基金",
    "wealth_product": "理财",
    "gold": "黄金",
    "cash": "现金",
    "crypto": "加密资产",
    "bond": "债券",
    "other": "其他",
}

POSITION_COLUMNS = [
    "provider",
    "account_name",
    "symbol",
    "instrument_name",
    "asset_type",
    "quantity",
    "price_original",
    "market_value_original",
    "currency",
    "market_value_usd",
    "valuation_date",
]


@dataclass(frozen=True)
class DashboardSummary:
    total_usd: float
    account_count: int
    provider_count: int
    position_count: int
    latest_valuation_date: str
    latest_import_status: str
    error_count: int
    cash_ratio: float
    top_holding_ratio: float
    top_asset_label: str


def empty_positions() -> pd.DataFrame:
    return pd.DataFrame(columns=POSITION_COLUMNS)


def normalize_positions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return empty_positions()
    df = df.copy()
    if "accounts" in df.columns:
        accounts = df["accounts"].apply(lambda value: value if isinstance(value, dict) else {})
        df["provider"] = accounts.apply(lambda value: value.get("provider", ""))
        df["account_name"] = accounts.apply(lambda value: value.get("account_name", ""))
    if "instruments" in df.columns:
        instruments = df["instruments"].apply(lambda value: value if isinstance(value, dict) else {})
        df["symbol"] = instruments.apply(lambda value: value.get("symbol", ""))
        df["instrument_name"] = instruments.apply(lambda value: value.get("name", ""))
        df["asset_type"] = instruments.apply(lambda value: value.get("asset_type", "other"))
    return coerce_position_columns(df)


def coerce_position_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for column in POSITION_COLUMNS:
        if column not in df.columns:
            df[column] = 0 if column in {"quantity", "price_original", "market_value_original", "market_value_usd"} else ""
    for column in ("quantity", "price_original", "market_value_original", "market_value_usd"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df["currency"] = df["currency"].fillna("").astype(str).str.upper()
    df["asset_type"] = df["asset_type"].fillna("other").astype(str).replace("", "other")
    for column in ("provider", "account_name", "symbol", "instrument_name"):
        df[column] = df[column].fillna("").astype(str)
    df["valuation_date"] = pd.to_datetime(df["valuation_date"], errors="coerce").dt.date.astype(str).replace("NaT", "")
    return df[POSITION_COLUMNS]


def load_sample_positions(root: Path) -> pd.DataFrame:
    sample_path = root / "sample_data" / "positions_demo.csv"
    if not sample_path.exists():
        return empty_positions()
    return coerce_position_columns(pd.read_csv(sample_path))


def allocation_summary(df: pd.DataFrame, group_by: str, label_column: str | None = None) -> pd.DataFrame:
    columns = [group_by, "market_value_usd", "weight"]
    if label_column:
        columns.insert(1, label_column)
    if df.empty:
        return pd.DataFrame(columns=columns)
    total = float(df["market_value_usd"].sum()) or 1.0
    grouped = df.groupby(group_by, as_index=False)["market_value_usd"].sum()
    grouped = grouped[grouped["market_value_usd"] > 0].sort_values("market_value_usd", ascending=False)
    grouped["weight"] = grouped["market_value_usd"] / total * 100
    if label_column == "asset_label":
        grouped[label_column] = grouped[group_by].map(ASSET_LABELS).fillna("其他")
    return grouped


def asset_summary(df: pd.DataFrame) -> pd.DataFrame:
    return allocation_summary(df, "asset_type", "asset_label")


def currency_summary(df: pd.DataFrame) -> pd.DataFrame:
    return allocation_summary(df, "currency")


def provider_summary(df: pd.DataFrame) -> pd.DataFrame:
    return allocation_summary(df, "provider")


def account_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["provider", "account_name", "currency", "market_value_original", "market_value_usd", "weight"])
    total = float(df["market_value_usd"].sum()) or 1.0
    grouped = (
        df.groupby(["provider", "account_name", "currency"], as_index=False)[["market_value_original", "market_value_usd"]]
        .sum()
        .sort_values("market_value_usd", ascending=False)
    )
    grouped["weight"] = grouped["market_value_usd"] / total * 100
    return grouped


def top_holdings(df: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*POSITION_COLUMNS, "asset_label", "weight"])
    total = float(df["market_value_usd"].sum()) or 1.0
    data = df.sort_values("market_value_usd", ascending=False).head(limit).copy()
    data["asset_label"] = data["asset_type"].map(ASSET_LABELS).fillna("其他")
    data["weight"] = data["market_value_usd"] / total * 100
    return data


def dashboard_summary(df: pd.DataFrame, imports: pd.DataFrame, errors: pd.DataFrame) -> DashboardSummary:
    accounts = df[["provider", "account_name"]].drop_duplicates() if not df.empty else pd.DataFrame()
    latest_date = ""
    if not df.empty:
        latest_date = max([value for value in df["valuation_date"].astype(str).tolist() if value], default="")
    latest_import_status = "暂无导入"
    if not imports.empty and "status" in imports.columns:
        latest_import_status = str(imports.iloc[0].get("status") or "未知")
    total = float(df["market_value_usd"].sum()) if not df.empty else 0.0
    cash = float(df.loc[df["asset_type"] == "cash", "market_value_usd"].sum()) if not df.empty else 0.0
    top = float(df["market_value_usd"].max()) if not df.empty else 0.0
    assets = asset_summary(df)
    top_asset_label = "暂无"
    if not assets.empty:
        top_asset_label = str(assets.iloc[0]["asset_label"])
    return DashboardSummary(
        total_usd=total,
        account_count=int(accounts.shape[0]),
        provider_count=int(df["provider"].replace("", pd.NA).dropna().nunique()) if not df.empty else 0,
        position_count=int(len(df)),
        latest_valuation_date=latest_date or "暂无估值",
        latest_import_status=latest_import_status,
        error_count=int(len(errors)) if errors is not None else 0,
        cash_ratio=(cash / total * 100) if total else 0.0,
        top_holding_ratio=(top / total * 100) if total else 0.0,
        top_asset_label=top_asset_label,
    )


def filter_positions(
    df: pd.DataFrame,
    *,
    asset_type: str = "all",
    provider: str = "all",
    account_name: str = "all",
    currency: str = "all",
    query: str = "",
    min_value: float = 0.0,
) -> pd.DataFrame:
    filtered = df.copy()
    if asset_type != "all":
        filtered = filtered[filtered["asset_type"] == asset_type]
    if provider != "all":
        filtered = filtered[filtered["provider"] == provider]
    if account_name != "all":
        filtered = filtered[filtered["account_name"] == account_name]
    if currency != "all":
        filtered = filtered[filtered["currency"] == currency]
    if min_value > 0:
        filtered = filtered[filtered["market_value_usd"] >= min_value]
    query = query.strip().lower()
    if query:
        haystack = (
            filtered["symbol"].astype(str)
            + " "
            + filtered["instrument_name"].astype(str)
            + " "
            + filtered["account_name"].astype(str)
            + " "
            + filtered["provider"].astype(str)
        ).str.lower()
        filtered = filtered[haystack.str.contains(query, regex=False)]
    return filtered.sort_values("market_value_usd", ascending=False)


def paginate(df: pd.DataFrame, page: int, page_size: int) -> tuple[pd.DataFrame, int]:
    page_size = max(1, page_size)
    total_pages = max(1, (len(df) + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    return df.iloc[start : start + page_size].copy(), total_pages
