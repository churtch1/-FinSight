from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal


AssetType = Literal[
    "stock",
    "fund",
    "wealth_product",
    "gold",
    "cash",
    "crypto",
    "bond",
    "other",
]

ASSET_TYPES: tuple[str, ...] = (
    "stock",
    "fund",
    "wealth_product",
    "gold",
    "cash",
    "crypto",
    "bond",
    "other",
)

TRANSACTION_TYPES: tuple[str, ...] = (
    "buy",
    "sell",
    "subscribe",
    "redeem",
    "deposit",
    "withdrawal",
    "dividend",
    "interest",
    "coupon",
    "fee",
    "tax",
    "cash_balance",
    "position_snapshot",
    "other",
)


@dataclass(frozen=True)
class NormalizedRow:
    account_name: str
    provider: str
    date: date
    type: str
    instrument_code: str
    instrument_name: str
    isin: str
    asset_type: str
    quantity: Decimal
    price: Decimal
    amount: Decimal
    currency: str
    fee: Decimal
    tax: Decimal
    description: str


def normalize_asset_type(value: str | None) -> str:
    if not value:
        return "other"
    normalized = value.strip().lower()
    aliases = {
        "股票": "stock",
        "stock": "stock",
        "equity": "stock",
        "基金": "fund",
        "fund": "fund",
        "理财": "wealth_product",
        "wealth": "wealth_product",
        "wealth_product": "wealth_product",
        "黄金": "gold",
        "gold": "gold",
        "现金": "cash",
        "cash": "cash",
        "crypto": "crypto",
        "加密货币": "crypto",
        "bond": "bond",
        "债券": "bond",
    }
    return aliases.get(normalized, "other")
