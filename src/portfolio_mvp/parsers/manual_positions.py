from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_mvp.fund_nav import FundNav, normalize_fund_code
from portfolio_mvp.models import NormalizedRow, normalize_asset_type


MANUAL_POSITION_COLUMNS: tuple[str, ...] = (
    "instrument_code",
    "instrument_name",
    "asset_type",
    "quantity",
    "price",
    "fund_nav",
    "fund_nav_date",
    "amount",
    "currency",
    "cost",
    "unrealized_pnl",
    "total_pnl",
    "pnl_pct",
    "description",
)


def parse_manual_position_records(
    records: list[dict[str, Any]],
    *,
    provider: str,
    account_name: str,
    valuation_date: date,
    fund_navs: dict[str, FundNav] | None = None,
) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    for index, raw in enumerate(records, start=1):
        if _is_blank_record(raw):
            continue
        try:
            rows.append(
                _parse_record(
                    raw,
                    provider=provider,
                    account_name=account_name,
                    valuation_date=valuation_date,
                    fund_navs=fund_navs or {},
                )
            )
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Manual position row {index}: {exc}") from exc
    return rows


def _parse_record(
    raw: dict[str, Any],
    *,
    provider: str,
    account_name: str,
    valuation_date: date,
    fund_navs: dict[str, FundNav],
) -> NormalizedRow:
    instrument_code = _text(raw.get("instrument_code"))
    asset_type = normalize_asset_type(_text(raw.get("asset_type")))
    instrument_name = normalize_manual_instrument_name(_text(raw.get("instrument_name")), asset_type) or instrument_code
    if not instrument_name:
        raise ValueError("instrument_code or instrument_name is required")

    quantity = _decimal(raw.get("quantity"))
    price = _decimal(raw.get("price"))
    amount = _decimal(raw.get("amount"))
    total_pnl = _optional_decimal(raw.get("total_pnl"))
    cost = _optional_decimal(raw.get("cost"))
    unrealized_pnl = _optional_decimal(raw.get("unrealized_pnl"))
    pnl_for_cost = total_pnl
    if asset_type == "gold" and unrealized_pnl is not None:
        pnl_for_cost = unrealized_pnl
        total_pnl = unrealized_pnl
    pnl_pct = _optional_pct(raw.get("pnl_pct"))
    quantity_source = _text(raw.get("quantity_source")) or "reported"
    estimate_note = ""
    if amount == 0 and quantity != 0 and price != 0:
        amount = quantity * price
    if amount == 0 and cost is not None and total_pnl is not None:
        amount = (cost + total_pnl).quantize(Decimal("0.01"))
    elif amount == 0 and total_pnl is not None and pnl_pct is not None and pnl_pct != 0:
        cost = (total_pnl / pnl_pct).quantize(Decimal("0.01"))
        amount = (cost + total_pnl).quantize(Decimal("0.01"))
    elif amount == 0 and cost is not None and pnl_pct is not None:
        amount = (cost * (Decimal("1") + pnl_pct)).quantize(Decimal("0.01"))
        total_pnl = (amount - cost).quantize(Decimal("0.01"))
    if amount != 0 and quantity == 0:
        nav = _fund_nav_for_record(raw, instrument_code, fund_navs)
        if asset_type == "fund" and nav is not None and nav > 0:
            quantity = (amount / nav).quantize(Decimal("0.000001"))
            price = nav
            quantity_source = "inferred"
            estimate_note = "Quantity inferred from market value and latest disclosed fund NAV."
        else:
            quantity = Decimal("1")
            quantity_source = "manual"
    if amount != 0 and price == 0 and quantity != 0:
        price = (amount / quantity).quantize(Decimal("0.000001"))
    if amount == 0:
        raise ValueError("amount is required unless quantity and price are provided")

    if cost is None and pnl_for_cost is not None:
        cost = (amount - pnl_for_cost).quantize(Decimal("0.01"))
    if cost is None and total_pnl is None and pnl_pct is not None:
        cost = (amount / (Decimal("1") + pnl_pct)).quantize(Decimal("0.01"))
        total_pnl = (amount - cost).quantize(Decimal("0.01"))
    elif cost is None and total_pnl is not None and pnl_pct is not None and pnl_pct != 0:
        cost = (total_pnl / pnl_pct).quantize(Decimal("0.01"))

    currency = (_text(raw.get("currency")) or "CNY").upper()
    return NormalizedRow(
        account_name=account_name,
        provider=provider,
        date=valuation_date,
        type="position_snapshot",
        instrument_code=instrument_code,
        instrument_name=instrument_name,
        isin="",
        asset_type=asset_type,
        quantity=quantity,
        price=price,
        amount=amount,
        currency=currency,
        fee=Decimal("0"),
        tax=Decimal("0"),
        description=_text(raw.get("description")) or f"Manual {provider} position snapshot",
        cost=cost,
        unrealized_pnl=unrealized_pnl,
        income=None,
        total_pnl=total_pnl,
        quantity_source=quantity_source,
        estimate_note=estimate_note,
    )


def _is_blank_record(raw: dict[str, Any]) -> bool:
    return not any(_text(raw.get(column)) for column in MANUAL_POSITION_COLUMNS)


def _decimal(value: Any) -> Decimal:
    text = _text(value)
    if not text:
        return Decimal("0")
    return Decimal(text.replace(",", ""))


def _optional_decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    return Decimal(text.replace(",", ""))


def _optional_pct(value: Any) -> Decimal | None:
    text = _text(value)
    if not text:
        return None
    normalized = text.replace(",", "").replace("%", "")
    value_decimal = Decimal(normalized)
    return value_decimal / Decimal("100")


def _fund_nav_for_record(raw: dict[str, Any], instrument_code: str, fund_navs: dict[str, FundNav]) -> Decimal | None:
    manual_nav = _optional_decimal(raw.get("fund_nav"))
    if manual_nav is not None:
        return manual_nav
    fund_code = normalize_fund_code(instrument_code)
    if not fund_code:
        return None
    nav = fund_navs.get(fund_code)
    return nav.unit_nav if nav is not None and nav.status == "ok" else None


def normalize_manual_instrument_name(name: str, asset_type: str) -> str:
    text = " ".join(_text(name).split())
    if asset_type != "wealth_product":
        return text
    marker = "持有"
    marker_index = text.find(marker)
    if marker_index == -1:
        return text
    return text[: marker_index + len(marker)].rstrip(" .。…")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "item"):
        value = value.item()
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text
