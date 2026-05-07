from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from portfolio_mvp.models import NormalizedRow


ALLOCATION_CATEGORIES: dict[str, tuple[str, str]] = {
    "基金相关产品": ("fund", "HSBC Fund Related Products"),
    "资管计划及信托计划": ("wealth_product", "HSBC Asset Management and Trust Plans"),
    "理财产品": ("wealth_product", "HSBC Wealth Products"),
    "QDII 债券": ("bond", "HSBC QDII Bonds"),
    "QDII 结构性票据": ("wealth_product", "HSBC QDII Structured Notes"),
    "结构性存款产品": ("wealth_product", "HSBC Structured Deposits"),
    "保险产品": ("other", "HSBC Insurance Products"),
    "现金 / 存款": ("cash", "HSBC Cash and Deposits"),
}

SECTION_CONFIG = (
    {
        "section_title": "基金相关产品",
        "section_end": "资管计划及信托计划",
        "asset_type": "fund",
    },
    {
        "section_title": "理财产品",
        "section_end": "您的持仓详情 —— 保险产品",
        "asset_type": "wealth_product",
    },
)

CURRENCY_MAP = {
    "人民币": "CNY",
    "美元": "USD",
    "港币": "HKD",
    "港元": "HKD",
}


def extract_text(path: str | Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def parse_hsbc_cn_pdf(path: str | Path) -> list[NormalizedRow]:
    """Best-effort HSBC China parser for wealth allocation reports."""
    text = _clean_text(extract_text(path))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    statement_date = _find_date(text) or date.today()
    account_name = _find_account_name(text)

    allocation_map = _parse_allocation_map(lines)
    detail_rows, covered_categories = _parse_product_detail_rows(lines, statement_date, account_name)
    if detail_rows:
        detail_rows.extend(
            _allocation_rows_from_map(
                allocation_map,
                statement_date,
                account_name,
                excluded_names=covered_categories,
            )
        )
        return detail_rows

    allocation_rows = _allocation_rows_from_map(allocation_map, statement_date, account_name)
    if allocation_rows:
        return allocation_rows

    amount = _parse_total_assets(text)
    if amount is None:
        return []
    return [
        NormalizedRow(
            account_name=account_name,
            provider="HSBC China",
            date=statement_date,
            type="cash_balance",
            instrument_code="CNY_CASH",
            instrument_name="CNY Cash",
            isin="",
            asset_type="cash",
            quantity=amount,
            price=Decimal("1"),
            amount=amount,
            currency="CNY",
            fee=Decimal("0"),
            tax=Decimal("0"),
            description="Extracted from HSBC China PDF total assets",
        )
    ]


def _clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    replacements = {
        "人⺠币": "人民币",
        "人⺠": "人民",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized


def _parse_allocation_map(lines: list[str]) -> dict[str, tuple[str, Decimal]]:
    output: dict[str, tuple[str, Decimal]] = {}
    for index, line in enumerate(lines[:-1]):
        match = re.fullmatch(r"(.+?)\s*\((\d+(?:\.\d+)?)%\)", line)
        if not match:
            continue
        category = _canonical_text(match.group(1))
        if category not in ALLOCATION_CATEGORIES:
            continue
        amount_match = re.search(r"(?:CNY|RMB|人民币)\s*([-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|-?\d+(?:\.\d{2})?)", lines[index + 1])
        if not amount_match:
            continue
        amount = Decimal(amount_match.group(1).replace(",", ""))
        output[category] = (match.group(2), amount)
    return output


def _allocation_rows_from_map(
    allocation_map: dict[str, tuple[str, Decimal]],
    statement_date: date,
    account_name: str,
    excluded_names: set[str] | None = None,
) -> list[NormalizedRow]:
    excluded_names = excluded_names or set()
    rows: list[NormalizedRow] = []
    for category, (weight, amount) in allocation_map.items():
        if amount == 0 or category in excluded_names:
            continue
        asset_type, english_name = ALLOCATION_CATEGORIES[category]
        rows.append(
            NormalizedRow(
                account_name=account_name,
                provider="HSBC China",
                date=statement_date,
                type="position_snapshot",
                instrument_code=_instrument_code(english_name),
                instrument_name=category,
                isin="",
                asset_type=asset_type,
                quantity=amount,
                price=Decimal("1"),
                amount=amount,
                currency="CNY",
                fee=Decimal("0"),
                tax=Decimal("0"),
                description=f"Extracted from HSBC China PDF allocation category; weight={weight}%",
            )
        )
    return rows


def _parse_product_detail_rows(lines: list[str], statement_date: date, account_name: str) -> tuple[list[NormalizedRow], set[str]]:
    rows: list[NormalizedRow] = []
    covered_categories: set[str] = set()
    for config in SECTION_CONFIG:
        section_rows = _parse_section_rows(
            lines,
            statement_date=statement_date,
            account_name=account_name,
            section_title=config["section_title"],
            section_end=config["section_end"],
            asset_type=config["asset_type"],
        )
        if section_rows:
            covered_categories.add(config["section_title"])
            rows.extend(section_rows)
    return rows, covered_categories


def _parse_section_rows(
    lines: list[str],
    statement_date: date,
    account_name: str,
    section_title: str,
    section_end: str,
    asset_type: str,
) -> list[NormalizedRow]:
    start = _find_line_index(lines, section_title)
    if start is None:
        return []
    end = _find_line_index(lines, section_end, start + 1)
    section_lines = lines[start:end] if end is not None else lines[start:]
    block_starts = [index for index, line in enumerate(section_lines) if line.startswith("价格日期:")]
    if not block_starts:
        return []

    product_names = _extract_product_names(section_lines, block_starts)
    rows: list[NormalizedRow] = []
    for block_index, start_index in enumerate(block_starts):
        block = section_lines[start_index : start_index + 15]
        if len(block) < 15:
            continue
        row = _build_detail_row(
            block,
            name=product_names[block_index] if block_index < len(product_names) else f"{section_title} {block_index + 1}",
            asset_type=asset_type,
            statement_date=statement_date,
            account_name=account_name,
        )
        if row is not None:
            rows.append(row)
    return rows


def _extract_product_names(section_lines: list[str], block_starts: list[int]) -> list[str]:
    tail_start = block_starts[-1] + 15
    tail_lines = section_lines[tail_start:]
    names = [line for line in tail_lines if _looks_like_product_name(line)]
    return names[: len(block_starts)]


def _looks_like_product_name(line: str) -> bool:
    if line.startswith("日期展示方式:"):
        return False
    if line.startswith("您暂未") or line.startswith("如需"):
        return False
    if line in ALLOCATION_CATEGORIES:
        return False
    if "——" in line:
        return False
    if re.search(r"\(\s*[A-Z0-9]{4,}\s*\)", line):
        return True
    if re.search(r"\(\s*\d{6}\s*\)", line):
        return True
    return False


def _build_detail_row(
    block: list[str],
    name: str,
    asset_type: str,
    statement_date: date,
    account_name: str,
) -> NormalizedRow | None:
    currency = _currency_code(block[1])
    amount = _parse_decimal(block[2])
    quantity, price = _parse_quantity_price(" ".join(block[3:5]))
    cost = _parse_decimal(block[6])
    unrealized_pnl = _parse_decimal(block[8])
    income = _parse_decimal(block[11])
    total_pnl = _parse_decimal(block[13])
    if amount is None:
        return None
    normalized_name = _canonical_text(name)
    return NormalizedRow(
        account_name=account_name,
        provider="HSBC China",
        date=statement_date,
        type="position_snapshot",
        instrument_code=_instrument_code(normalized_name),
        instrument_name=normalized_name,
        isin="",
        asset_type=asset_type,
        quantity=quantity if quantity is not None else amount,
        price=price if price is not None else Decimal("1"),
        amount=amount,
        currency=currency,
        fee=Decimal("0"),
        tax=Decimal("0"),
        description=f"Extracted from HSBC China PDF product detail: {normalized_name}",
        cost=cost,
        unrealized_pnl=unrealized_pnl,
        income=income,
        total_pnl=total_pnl,
    )


def _parse_total_assets(text: str) -> Decimal | None:
    patterns = (
        r"总资产合计\s*(?:CNY|RMB|人民币)\s*([-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|-?\d+(?:\.\d{2})?)",
        r"总资产(?:\s*\([^)]*\))?\s*[:：]?\s*(?:CNY|RMB|人民币)\s*([-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|-?\d+(?:\.\d{2})?)",
        r"(?:账户余额|存款余额|现金余额)[^\d-]{0,40}([-+]?\d{1,3}(?:,\d{3})*(?:\.\d{2})?|-?\d+(?:\.\d{2})?)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return Decimal(match.group(1).replace(",", ""))
    return None


def _find_date(text: str) -> date | None:
    for pattern in (
        r"(\d{4})\s*(?:[-/年])\s*(\d{1,2})\s*(?:[-/月])\s*(\d{1,2})\s*(?:日)?",
        r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groups()
        if len(groups[0]) == 4:
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        return date(int(groups[2]), int(groups[1]), int(groups[0]))
    return None


def _find_account_name(text: str) -> str:
    match = re.search(r"(?:账户|账号|帐号|户口|Account|Account Number)[^\n:：]*[:：]?\s*([A-Za-z0-9*\- ]{4,})", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b(CNHSBC\d+)\b", text)
    if match:
        return match.group(1)
    return "HSBC China"


def _currency_code(value: str) -> str:
    return CURRENCY_MAP.get(_canonical_text(value), "CNY")


def _parse_decimal(value: str) -> Decimal | None:
    match = re.search(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?", value)
    if not match:
        return None
    return Decimal(match.group(0).replace(",", ""))


def _parse_quantity_price(value: str) -> tuple[Decimal | None, Decimal | None]:
    quantity_match = re.search(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*份", value)
    price_match = re.search(r"@\s*(?:人民币|美元|港币|港元|CNY|USD|HKD)?\s*([-+]?\d[\d,]*(?:\.\d+)?)", value)
    quantity = Decimal(quantity_match.group(1).replace(",", "")) if quantity_match else None
    price = Decimal(price_match.group(1).replace(",", "")) if price_match else None
    return quantity, price


def _find_line_index(lines: list[str], target: str, start: int = 0) -> int | None:
    for index in range(start, len(lines)):
        if _canonical_text(lines[index]) == target:
            return index
    return None


def _canonical_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _instrument_code(value: str) -> str:
    code_match = re.search(r"\(\s*([A-Z0-9]{4,}|\d{6})\s*\)", value)
    if code_match:
        return code_match.group(1)
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
