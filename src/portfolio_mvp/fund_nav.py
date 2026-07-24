from __future__ import annotations

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests

from portfolio_mvp.config import Settings, get_settings


@dataclass(frozen=True)
class FundNav:
    fund_code: str
    fund_name: str
    unit_nav: Decimal
    nav_date: date
    accumulated_nav: Decimal | None = None
    announced_at: datetime | None = None
    source: str = "eastmoney"
    status: str = "ok"
    error_message: str = ""


class FundNavProvider:
    def fetch_one(self, fund_code: str) -> FundNav:
        raise NotImplementedError

    def fetch_many(self, fund_codes: list[str]) -> dict[str, FundNav]:
        navs: dict[str, FundNav] = {}
        for fund_code in fund_codes:
            try:
                nav = self.fetch_one(fund_code)
            except Exception as exc:
                nav = FundNav(
                    fund_code=normalize_fund_code(fund_code),
                    fund_name="",
                    unit_nav=Decimal("0"),
                    nav_date=date.today(),
                    source=self.__class__.__name__,
                    status="error",
                    error_message=str(exc),
                )
            navs[nav.fund_code] = nav
        return navs


class EastmoneyFundNavProvider(FundNavProvider):
    def __init__(self, settings: Settings | None = None, timeout: int = 8) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout

    def fetch_one(self, fund_code: str) -> FundNav:
        normalized = normalize_fund_code(fund_code)
        if not normalized:
            raise ValueError("fund_code is required")
        url = self.settings.fund_nav_api_url.format(fund_code=normalized)
        separator = "&" if "?" in url else "?"
        response = requests.get(f"{url}{separator}rt={int(time.time() * 1000)}", timeout=self.timeout)
        response.raise_for_status()
        try:
            return parse_eastmoney_nav_response(normalized, response.text)
        except ValueError:
            fallback = requests.get(
                f"https://fund.eastmoney.com/pingzhongdata/{normalized}.js?v={int(time.time() * 1000)}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": f"https://fund.eastmoney.com/{normalized}.html"},
                timeout=self.timeout,
            )
            fallback.raise_for_status()
            return parse_eastmoney_pingzhongdata_response(normalized, fallback.text)


def normalize_fund_code(value: str | None) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d{6}", text)
    return match.group(0) if match else ""


def parse_eastmoney_nav_response(fund_code: str, text: str) -> FundNav:
    match = re.search(r"\((\{.*\})\)\s*;?\s*$", text.strip(), flags=re.S)
    if not match:
        raise ValueError("Fund NAV response is not valid JSONP")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise ValueError("Fund NAV response payload is not an object")

    code = normalize_fund_code(str(payload.get("fundcode") or fund_code))
    try:
        unit_nav = _decimal(payload.get("dwjz"))
    except ValueError as exc:
        raise ValueError(f"Fund NAV is missing for {code or fund_code}") from exc
    if unit_nav <= 0:
        raise ValueError(f"Fund NAV is missing for {code or fund_code}")

    nav_date = _date(payload.get("jzrq"))
    announced_at = _datetime(payload.get("gztime"))
    return FundNav(
        fund_code=code or fund_code,
        fund_name=str(payload.get("name") or "").strip(),
        unit_nav=unit_nav,
        accumulated_nav=_optional_decimal(payload.get("ljjz")),
        nav_date=nav_date,
        announced_at=announced_at,
        source="eastmoney",
        status="ok",
    )


def parse_eastmoney_pingzhongdata_response(fund_code: str, text: str) -> FundNav:
    code = normalize_fund_code(fund_code)
    name_match = re.search(r'var\s+fS_name\s*=\s*"([^"]*)"', text)
    code_match = re.search(r'var\s+fS_code\s*=\s*"([^"]*)"', text)
    trend_match = re.search(r"var\s+Data_netWorthTrend\s*=\s*(\[.*?\]);", text, flags=re.S)
    if not trend_match:
        raise ValueError(f"Fund NAV trend is missing for {code or fund_code}")
    trend = json.loads(trend_match.group(1))
    if not isinstance(trend, list) or not trend:
        raise ValueError(f"Fund NAV trend is empty for {code or fund_code}")
    latest = trend[-1]
    unit_nav = _decimal(latest.get("y"))
    if unit_nav <= 0:
        raise ValueError(f"Fund NAV is missing for {code or fund_code}")
    timestamp = int(latest.get("x"))
    nav_date = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date()
    return FundNav(
        fund_code=normalize_fund_code(code_match.group(1) if code_match else code) or code or fund_code,
        fund_name=name_match.group(1).strip() if name_match else "",
        unit_nav=unit_nav,
        accumulated_nav=None,
        nav_date=nav_date,
        announced_at=None,
        source="eastmoney_pingzhongdata",
        status="ok",
    )


def parse_fund_nav_csv(path: str | Path) -> list[FundNav]:
    navs: list[FundNav] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for line_number, raw in enumerate(reader, start=2):
            try:
                fund_code = normalize_fund_code(raw.get("fund_code"))
                if not fund_code:
                    raise ValueError("fund_code is required")
                navs.append(
                    FundNav(
                        fund_code=fund_code,
                        fund_name=str(raw.get("fund_name") or "").strip(),
                        unit_nav=_decimal(raw.get("unit_nav")),
                        accumulated_nav=_optional_decimal(raw.get("accumulated_nav")),
                        nav_date=_date(raw.get("nav_date")),
                        announced_at=_datetime(raw.get("announced_at")),
                        source=str(raw.get("source") or "manual").strip() or "manual",
                        status=str(raw.get("status") or "ok").strip() or "ok",
                        error_message=str(raw.get("error_message") or "").strip(),
                    )
                )
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"Fund NAV CSV line {line_number}: {exc}") from exc
    return navs


def latest_nav_map(rows: list[dict[str, Any]]) -> dict[str, FundNav]:
    output: dict[str, FundNav] = {}
    for row in rows:
        try:
            nav = FundNav(
                fund_code=normalize_fund_code(str(row.get("fund_code") or "")),
                fund_name=str(row.get("fund_name") or ""),
                unit_nav=Decimal(str(row.get("unit_nav"))),
                accumulated_nav=_optional_decimal(row.get("accumulated_nav")),
                nav_date=_date(row.get("nav_date")),
                announced_at=_datetime(row.get("announced_at")),
                source=str(row.get("source") or "cached"),
                status=str(row.get("status") or "ok"),
                error_message=str(row.get("error_message") or ""),
            )
        except (InvalidOperation, ValueError, TypeError):
            continue
        if not nav.fund_code or nav.status != "ok":
            continue
        existing = output.get(nav.fund_code)
        if existing is None or nav.nav_date >= existing.nav_date:
            output[nav.fund_code] = nav
    return output


def _decimal(value: Any) -> Decimal:
    text = str(value or "").replace(",", "").strip()
    if not text:
        raise ValueError("decimal value is required")
    return Decimal(text)


def _optional_decimal(value: Any) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    return Decimal(text) if text else None


def _date(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("date value is required")
    return date.fromisoformat(text[:10])


def _datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
