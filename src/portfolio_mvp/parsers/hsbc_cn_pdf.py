from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from portfolio_mvp.models import NormalizedRow


def extract_text(path: str | Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def parse_hsbc_cn_pdf(path: str | Path) -> list[NormalizedRow]:
    """Best-effort HSBC China parser.

    This is intentionally conservative until a脱敏样例 is available. It extracts
    obvious CNY cash balance lines and records everything else as pending parser
    work through the import status/error path.
    """
    text = extract_text(path)
    rows: list[NormalizedRow] = []
    statement_date = _find_date(text) or date.today()
    account_name = _find_account_name(text)

    cash_patterns = [
        r"(?:总资产|资产合计|账户余额|存款余额)[^\d-]*([0-9,]+\.\d{2}|[0-9,]+)",
        r"(?:CNY|人民币|RMB)[^\d-]*([0-9,]+\.\d{2}|[0-9,]+)",
    ]
    for pattern in cash_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = Decimal(match.group(1).replace(",", ""))
            rows.append(
                NormalizedRow(
                    account_name=account_name,
                    provider="HSBC China",
                    date=statement_date,
                    type="cash_balance",
                    instrument_code="CNY CASH",
                    instrument_name="CNY Cash",
                    isin="",
                    asset_type="cash",
                    quantity=amount,
                    price=Decimal("1"),
                    amount=amount,
                    currency="CNY",
                    fee=Decimal("0"),
                    tax=Decimal("0"),
                    description="Extracted from HSBC China PDF",
                )
            )
            break
    return rows


def _find_date(text: str) -> date | None:
    for pattern in (r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})"):
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        if len(groups[0]) == 4:
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        return date(int(groups[2]), int(groups[1]), int(groups[0]))
    return None


def _find_account_name(text: str) -> str:
    match = re.search(r"(?:账户|Account)[^\n:：]*[:：]?\s*([A-Za-z0-9*\- ]{4,})", text)
    if match:
        return match.group(1).strip()
    return "HSBC China"

