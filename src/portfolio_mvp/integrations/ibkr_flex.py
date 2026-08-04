from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import requests


FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


@dataclass(frozen=True)
class FlexPosition:
    account_id: str
    report_date: date
    asset_class: str
    currency: str
    symbol: str
    description: str
    conid: str
    security_id: str
    security_id_type: str
    cusip: str
    isin: str
    quantity: Decimal
    multiplier: Decimal
    mark_price: Decimal
    position_value: Decimal
    cost_basis_money: Decimal | None
    unrealized_pnl: Decimal | None
    accrued_interest: Decimal | None


class IbkrFlexClient:
    def __init__(self, token: str, query_id: str, timeout: int = 20) -> None:
        self.token = token.strip()
        self.query_id = query_id.strip()
        self.timeout = timeout
        if not self.token:
            raise ValueError("IBKR_FLEX_TOKEN is required")
        if not self.query_id:
            raise ValueError("IBKR_FLEX_QUERY_ID is required")

    def fetch_positions(self) -> list[FlexPosition]:
        headers = {"User-Agent": "FinSight/1.0"}
        response = requests.get(
            f"{FLEX_BASE_URL}/SendRequest",
            params={"t": self.token, "q": self.query_id, "v": "3"},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        _raise_flex_error(root)
        reference_code = _child_text(root, "ReferenceCode")
        response_url = _child_text(root, "Url") or f"{FLEX_BASE_URL}/GetStatement"
        if not reference_code:
            raise RuntimeError("IBKR Flex did not return a reference code")

        for attempt in range(6):
            report = requests.get(
                response_url,
                params={"t": self.token, "q": reference_code, "v": "3"},
                headers=headers,
                timeout=self.timeout,
            )
            report.raise_for_status()
            report_root = ET.fromstring(report.text)
            error_code = _child_text(report_root, "ErrorCode")
            if error_code in {"1003", "1019"} and attempt < 5:
                time.sleep(2)
                continue
            _raise_flex_error(report_root)
            return parse_flex_positions(report.text)
        raise RuntimeError("IBKR Flex report was not ready in time")


def parse_flex_positions(text: str) -> list[FlexPosition]:
    root = ET.fromstring(text)
    rows: list[FlexPosition] = []
    for element in root.iter():
        if _local_name(element.tag) != "OpenPosition":
            continue
        raw = element.attrib
        rows.append(
            FlexPosition(
                account_id=_attr(raw, "accountId"),
                report_date=_date(_attr(raw, "reportDate")),
                asset_class=_attr(raw, "assetCategory", "assetClass"),
                currency=_attr(raw, "currency").upper(),
                symbol=_attr(raw, "symbol"),
                description=_attr(raw, "description"),
                conid=_attr(raw, "conid"),
                security_id=_attr(raw, "securityID", "securityId"),
                security_id_type=_attr(raw, "securityIDType", "securityIdType"),
                cusip=_attr(raw, "cusip"),
                isin=_attr(raw, "isin"),
                quantity=_decimal(_attr(raw, "position", "quantity")),
                multiplier=_decimal(_attr(raw, "multiplier"), default="1"),
                mark_price=_decimal(_attr(raw, "markPrice")),
                position_value=_decimal(_attr(raw, "positionValue")),
                cost_basis_money=_optional_decimal(_attr(raw, "costBasisMoney")),
                unrealized_pnl=_optional_decimal(
                    _attr(raw, "fifoPnlUnrealized", "unrealizedPnl", "unrealizedPL")
                ),
                accrued_interest=_optional_decimal(_attr(raw, "accruedInterest")),
            )
        )
    return rows


def sync_flex_positions(client: Any, positions: list[FlexPosition]) -> int:
    if not positions:
        return 0
    account_rows = client.table("accounts").select("id,account_name,account_number,provider").eq("provider", "IBKR").execute().data or []
    account_map: dict[str, str] = {}
    for row in account_rows:
        for value in (row.get("account_name"), row.get("account_number")):
            if value:
                account_map[str(value)] = str(row["id"])

    instruments = client.table("instruments").select("id,symbol,isin,currency,name,asset_type").execute().data or []
    by_symbol = {
        (str(row.get("symbol") or "").upper(), str(row.get("currency") or "").upper()): row
        for row in instruments
        if row.get("symbol")
    }
    by_isin = {str(row.get("isin") or "").upper(): row for row in instruments if row.get("isin")}
    updated = 0
    open_instruments_by_account: dict[str, set[str]] = {}
    report_dates_by_account: dict[str, date] = {}

    for position in positions:
        account_uuid = account_map.get(position.account_id)
        if not account_uuid:
            continue
        conid_symbol = f"IBCID{position.conid}" if position.conid else ""
        instrument = (
            by_isin.get(position.isin.upper())
            or by_symbol.get((conid_symbol.upper(), position.currency))
            or by_symbol.get((position.symbol.upper(), position.currency))
        )
        if not instrument:
            continue
        instrument_id = str(instrument["id"])
        open_instruments_by_account.setdefault(account_uuid, set()).add(instrument_id)
        current_report_date = report_dates_by_account.get(account_uuid)
        if current_report_date is None or position.report_date > current_report_date:
            report_dates_by_account[account_uuid] = position.report_date
        instrument_updates: dict[str, Any] = {}
        if position.description and str(instrument.get("name") or "").startswith(("US-T", "IBCID")):
            instrument_updates["name"] = position.description
        if position.isin and not instrument.get("isin"):
            instrument_updates["isin"] = position.isin
        if instrument_updates:
            client.table("instruments").update(instrument_updates).eq("id", instrument_id).execute()

        pnl = position.unrealized_pnl
        cost = position.cost_basis_money
        payload: dict[str, Any] = {
            "account_id": account_uuid,
            "instrument_id": instrument_id,
            "quantity": str(position.quantity),
            "price_original": str(position.mark_price),
            "market_value_original": str(position.position_value),
            "currency": position.currency,
            "market_value_usd": str(position.position_value) if position.currency == "USD" else None,
            "fx_rate_to_usd": "1" if position.currency == "USD" else None,
            "fx_rate_source": "ibkr_flex",
            "fx_rate_date": position.report_date.isoformat(),
            "valuation_date": position.report_date.isoformat(),
            "quantity_source": "reported",
            "estimate_note": "Official prior-business-day IBKR Flex mark price.",
        }
        if cost is not None:
            payload["cost_original"] = str(cost)
        if pnl is not None:
            payload["unrealized_pnl_original"] = str(pnl)
            payload["total_pnl_original"] = str(pnl)
        if cost not in (None, Decimal("0")) and pnl is not None:
            payload["pnl_pct"] = str((pnl / abs(cost)).quantize(Decimal("0.000001")))
        client.table("positions_current").upsert(
            payload,
            on_conflict="account_id,instrument_id,valuation_date",
        ).execute()
        updated += 1

    for account_uuid, report_date in report_dates_by_account.items():
        _reconcile_flex_account_snapshot(
            client,
            account_uuid=account_uuid,
            report_date=report_date,
            open_instrument_ids=open_instruments_by_account.get(account_uuid, set()),
        )
    return updated


def _reconcile_flex_account_snapshot(
    client: Any,
    *,
    account_uuid: str,
    report_date: date,
    open_instrument_ids: set[str],
) -> None:
    """Close securities absent from Flex and carry non-security rows into a complete snapshot."""
    rows = (
        client.table("positions_current")
        .select(
            "account_id,instrument_id,quantity,price_original,market_value_original,currency,"
            "market_value_usd,fx_rate_to_usd,fx_rate_source,fx_rate_date,valuation_date,"
            "cost_original,unrealized_pnl_original,income_original,total_pnl_original,pnl_pct,"
            "quantity_source,estimate_note,instruments(asset_type)"
        )
        .eq("account_id", account_uuid)
        .execute()
        .data
        or []
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        instrument_id = str(row.get("instrument_id") or "")
        existing = latest.get(instrument_id)
        if existing is None or str(row.get("valuation_date") or "") > str(existing.get("valuation_date") or ""):
            latest[instrument_id] = row

    allowed = {
        "account_id", "instrument_id", "quantity", "price_original", "market_value_original",
        "currency", "market_value_usd", "fx_rate_to_usd", "fx_rate_source", "fx_rate_date",
        "cost_original", "unrealized_pnl_original", "income_original", "total_pnl_original",
        "pnl_pct", "quantity_source", "estimate_note",
    }
    security_types = {"stock", "fund", "bond"}
    for instrument_id, row in latest.items():
        if instrument_id in open_instrument_ids:
            continue
        payload = {key: value for key, value in row.items() if key in allowed}
        payload["valuation_date"] = report_date.isoformat()
        asset_type = str((row.get("instruments") or {}).get("asset_type") or "")
        if asset_type in security_types:
            payload.update(
                {
                    "quantity": "0",
                    "market_value_original": "0",
                    "market_value_usd": "0",
                    "cost_original": "0",
                    "unrealized_pnl_original": "0",
                    "income_original": "0",
                    "total_pnl_original": "0",
                    "pnl_pct": "0",
                    "fx_rate_source": "ibkr_flex:closed",
                    "fx_rate_date": report_date.isoformat(),
                    "estimate_note": "Closed because the security is absent from the latest IBKR Flex open-positions report.",
                }
            )
        client.table("positions_current").upsert(
            payload,
            on_conflict="account_id,instrument_id,valuation_date",
        ).execute()


def _raise_flex_error(root: ET.Element) -> None:
    status = _child_text(root, "Status")
    error_code = _child_text(root, "ErrorCode")
    if status.lower() == "fail" or error_code:
        message = _child_text(root, "ErrorMessage") or "Unknown IBKR Flex error"
        raise RuntimeError(f"IBKR Flex {error_code or 'error'}: {message}")


def _child_text(root: ET.Element, name: str) -> str:
    wanted = name.lower()
    for element in root.iter():
        if _local_name(element.tag).lower() == wanted:
            return str(element.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(raw: dict[str, str], *names: str) -> str:
    for name in names:
        if name in raw:
            return str(raw[name] or "").strip()
    return ""


def _decimal(value: str, default: str = "0") -> Decimal:
    return Decimal(str(value or default).replace(",", ""))


def _optional_decimal(value: str) -> Decimal | None:
    return _decimal(value) if str(value or "").strip() else None


def _date(value: str) -> date:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return date.fromisoformat(text[:10])
