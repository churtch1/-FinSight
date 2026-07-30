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
from html import unescape

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


@dataclass(frozen=True)
class OffshoreFund:
    fund_code: str
    fund_name: str
    isin: str
    currency: str
    urls: tuple[str, ...]


OFFSHORE_FUNDS: dict[str, OffshoreFund] = {
    "IPFD2240": OffshoreFund(
        fund_code="IPFD2240",
        fund_name="联博美国增长基金 A类美元累积",
        isin="LU0079474960",
        currency="USD",
        urls=(
            "https://www.boursorama.com/bourse/opcvm/cours/MP-306315/",
            "https://www.kgi.com.hk/en/products-overview/wealth-products/mutual-funds/"
            "fund-detail?funds=lu0079474960%3Ausd%3A0",
            "https://www.finanzen.net/fonds/ab-i-american-growth-portfolio-a-lu0079474960",
        ),
    ),
    "IPFD3391": OffshoreFund(
        fund_code="IPFD3391",
        fund_name="骏利亨德森全球科技领先基金 A2美元累积",
        isin="LU0070992663",
        currency="USD",
        urls=(
            "https://www.janushenderson.com/en-be/advisor/product/"
            "janus-henderson-horizon-global-technology-leaders-fund/?identifier=LU0070992663",
            "https://www.chiefgroup.com.hk/en/funds/fundsinfo/dp?secid=F0GBR04E8V",
            "https://www.finanzen.net/fonds/"
            "janus-henderson-horizon-global-technology-leaders-fund-lu0070992663",
        ),
    ),
}


class OffshoreFundNavProvider(FundNavProvider):
    """Fetch daily disclosed NAVs for the exact HSBC offshore share classes."""

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout

    def fetch_one(self, fund_code: str) -> FundNav:
        normalized = normalize_fund_code(fund_code)
        fund = OFFSHORE_FUNDS.get(normalized)
        if fund is None:
            raise ValueError(f"Unsupported offshore fund: {fund_code}")

        errors: list[str] = []
        for url in fund.urls:
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; PortfolioDashboard/1.0)"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                unit_nav, nav_date = parse_offshore_fund_page(response.text, fund.currency)
                return FundNav(
                    fund_code=fund.fund_code,
                    fund_name=fund.fund_name,
                    unit_nav=unit_nav,
                    nav_date=nav_date,
                    source=f"offshore:{response.url.split('/')[2]}:{fund.isin}",
                    status="ok",
                )
            except Exception as exc:
                errors.append(f"{url}: {exc}")
        raise ValueError("; ".join(errors))


class AutomaticFundNavProvider(FundNavProvider):
    """Dispatch domestic fund codes and HSBC offshore product codes."""

    def __init__(self, settings: Settings | None = None, timeout: int = 8) -> None:
        self.domestic = EastmoneyFundNavProvider(settings=settings, timeout=timeout)
        self.offshore = OffshoreFundNavProvider(timeout=max(timeout, 10))

    def fetch_one(self, fund_code: str) -> FundNav:
        normalized = normalize_fund_code(fund_code)
        if normalized in OFFSHORE_FUNDS:
            return self.offshore.fetch_one(normalized)
        return self.domestic.fetch_one(normalized)


def normalize_fund_code(value: str | None) -> str:
    text = str(value or "").strip().upper()
    offshore_match = re.search(r"\bIPFD\d{4}\b", text)
    if offshore_match:
        return offshore_match.group(0)
    match = re.search(r"\d{6}", text)
    return match.group(0) if match else ""


def parse_offshore_fund_page(text: str, currency: str = "USD") -> tuple[Decimal, date]:
    """Extract a formal daily NAV and its date from supported public fund pages."""
    # Boursorama embeds the complete daily NAV series in the server-rendered page.
    series = re.findall(r'"period":"(\d{2})\\?/(\d{2})","value":([0-9.]+)', text)
    if series:
        day, month, value = series[-1]
        today = date.today()
        year = today.year
        candidate = date(year, int(month), int(day))
        if candidate > today:
            candidate = date(year - 1, int(month), int(day))
        return _decimal(value), candidate

    plain = unescape(re.sub(r"<[^>]+>", " ", text))
    plain = re.sub(r"\s+", " ", plain)
    currency_pattern = re.escape(currency.upper())
    nav_patterns = (
        rf"\bNAV\b[^0-9]{{0,80}}{currency_pattern}\s*([0-9][0-9,.]*)",
        rf"\bNAV\b[^0-9]{{0,80}}([0-9][0-9,.]*)\s*{currency_pattern}",
        rf"\b(?:Unit Price|Kurs)\b[^0-9]{{0,80}}([0-9][0-9,.]*)",
    )
    nav_match = next((re.search(pattern, plain, flags=re.I) for pattern in nav_patterns if re.search(pattern, plain, flags=re.I)), None)
    if nav_match is None:
        raise ValueError("Daily NAV is missing from offshore fund page")
    unit_nav = _decimal(nav_match.group(1))
    if unit_nav <= 0:
        raise ValueError("Daily NAV must be positive")

    date_patterns = (
        r"(?:As of|NAV(?:/Kurs)?|NAV date|Kursdatum)[^0-9]{0,30}(\d{4}-\d{2}-\d{2})",
        r"(?:As of|NAV(?:/Kurs)?|NAV date|Kursdatum)[^0-9]{0,30}(\d{2}/\d{2}/\d{4})",
        r"(?:As of|NAV(?:/Kurs)?|NAV date|Kursdatum)[^0-9]{0,30}(\d{2}\.\d{2}\.\d{2,4})",
    )
    date_match = next((re.search(pattern, plain, flags=re.I) for pattern in date_patterns if re.search(pattern, plain, flags=re.I)), None)
    if date_match is None:
        raise ValueError("NAV date is missing from offshore fund page")
    raw_date = date_match.group(1)
    if "-" in raw_date:
        nav_date = date.fromisoformat(raw_date)
    elif "/" in raw_date:
        nav_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
    else:
        nav_date = datetime.strptime(raw_date, "%d.%m.%Y" if len(raw_date.split(".")[-1]) == 4 else "%d.%m.%y").date()
    return unit_nav, nav_date


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
