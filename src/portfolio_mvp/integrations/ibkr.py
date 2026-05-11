from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from portfolio_mvp.config import Settings, get_settings
from portfolio_mvp.models import NormalizedRow


ACCOUNT_SUMMARY_TAGS = (
    "BaseCurrency",
    "NetLiquidation",
    "TotalCashValue",
    "SettledCash",
    "BuyingPower",
    "AvailableFunds",
)

CASH_TAG_PRIORITY = {
    "CashBalance": 0,
    "TotalCashBalance": 1,
    "TotalCashValue": 2,
    "SettledCash": 3,
}

IGNORED_CASH_CURRENCIES = {"", "BASE"}


@dataclass(frozen=True)
class IbkrSyncData:
    accounts: list[str]
    account_summaries: dict[str, dict[str, str]]
    rows: list[NormalizedRow]


def sync_ibkr_rows(account: str = "all", settings: Settings | None = None) -> list[NormalizedRow]:
    return sync_ibkr_data(account=account, settings=settings).rows


def sync_ibkr_data(
    account: str = "all",
    settings: Settings | None = None,
    ib_factory: Callable[[], Any] | None = None,
) -> IbkrSyncData:
    settings = settings or get_settings()
    _ensure_thread_event_loop()
    ib_factory = ib_factory or _load_ib_factory()

    ib = ib_factory()
    try:
        ib.connect(settings.ibkr_host, settings.ibkr_port, clientId=settings.ibkr_client_id, timeout=8)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to IBKR at {settings.ibkr_host}:{settings.ibkr_port}. "
            "Start IB Gateway/TWS and enable API connections."
        ) from exc

    try:
        managed_accounts = list(ib.managedAccounts() or [])
        selected_accounts = _select_accounts(account, managed_accounts)
        account_summaries = _account_summaries(ib, selected_accounts)
        today = date.today()

        rows: list[NormalizedRow] = []
        rows.extend(_position_rows(ib, selected_accounts, today))
        rows.extend(_cash_rows(ib, selected_accounts, today))
        rows.extend(_execution_rows(ib, selected_accounts, today))

        accounts = selected_accounts or sorted({row.account_name for row in rows}) or managed_accounts
        return IbkrSyncData(accounts=accounts, account_summaries=account_summaries, rows=rows)
    finally:
        ib.disconnect()


def _ensure_thread_event_loop() -> None:
    try:
        asyncio.get_running_loop()
        return
    except RuntimeError:
        pass

    policy = asyncio.get_event_loop_policy()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            policy.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _load_ib_factory() -> Callable[[], Any]:
    try:
        from ib_insync import IB
    except ImportError as exc:
        raise RuntimeError("ib-insync is not installed. Run pip install -r requirements.txt.") from exc
    return IB


def _select_accounts(account: str, managed_accounts: list[str]) -> list[str]:
    if account == "all":
        return managed_accounts
    selected = [item.strip() for item in account.split(",") if item.strip()]
    missing = sorted(set(selected) - set(managed_accounts))
    if managed_accounts and missing:
        raise RuntimeError(f"IBKR account not found: {', '.join(missing)}. Available accounts: {', '.join(managed_accounts)}.")
    return selected


def _account_summaries(ib: Any, selected_accounts: list[str]) -> dict[str, dict[str, str]]:
    summaries: dict[str, dict[str, str]] = {}
    try:
        values = list(ib.accountSummary() or [])
    except Exception:
        values = []

    selected = set(selected_accounts)
    for value in values:
        account = _text(getattr(value, "account", ""))
        if selected and account not in selected:
            continue
        tag = _text(getattr(value, "tag", ""))
        if tag not in ACCOUNT_SUMMARY_TAGS:
            continue
        raw_value = _text(getattr(value, "value", ""))
        currency = _text(getattr(value, "currency", ""))
        summaries.setdefault(account, {})[tag] = currency if tag == "BaseCurrency" and currency else raw_value
    return summaries


def _position_rows(ib: Any, selected_accounts: list[str], today: date) -> list[NormalizedRow]:
    rows: list[NormalizedRow] = []
    selected = set(selected_accounts)
    portfolio_items = list(ib.portfolio() or [])
    for item in portfolio_items:
        if selected and item.account not in selected:
            continue
        contract = item.contract
        rows.append(
            _position_row(
                account_name=item.account,
                contract=contract,
                quantity=_decimal(getattr(item, "position", 0)),
                price=_decimal(getattr(item, "marketPrice", 0)),
                amount=_decimal(getattr(item, "marketValue", 0)),
                cost=_position_cost(item),
                unrealized_pnl=_optional_decimal(getattr(item, "unrealizedPNL", None)),
                total_pnl=_optional_decimal(getattr(item, "unrealizedPNL", None)),
                today=today,
                description="IBKR portfolio snapshot",
            )
        )

    if rows:
        return rows

    for position in list(_call_optional(ib, "positions") or []):
        if selected and position.account not in selected:
            continue
        contract = position.contract
        quantity = _decimal(getattr(position, "position", 0))
        price = _decimal(getattr(position, "avgCost", 0))
        rows.append(
            _position_row(
                account_name=position.account,
                contract=contract,
                quantity=quantity,
                price=price,
                amount=(quantity * price).quantize(Decimal("0.01")),
                cost=(quantity * price).quantize(Decimal("0.01")),
                unrealized_pnl=None,
                total_pnl=None,
                today=today,
                description="IBKR position snapshot using average cost",
            )
        )
    return rows


def _position_row(
    account_name: str,
    contract: Any,
    quantity: Decimal,
    price: Decimal,
    amount: Decimal,
    cost: Decimal | None,
    unrealized_pnl: Decimal | None,
    total_pnl: Decimal | None,
    today: date,
    description: str,
) -> NormalizedRow:
    return NormalizedRow(
        account_name=account_name,
        provider="IBKR",
        date=today,
        type="position_snapshot",
        instrument_code=_contract_code(contract),
        instrument_name=_contract_name(contract),
        isin="",
        asset_type=_asset_type_for_contract(contract),
        quantity=quantity,
        price=price,
        amount=amount,
        currency=_text(getattr(contract, "currency", "")) or "USD",
        fee=Decimal("0"),
        tax=Decimal("0"),
        description=description,
        cost=cost,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
    )


def _cash_rows(ib: Any, selected_accounts: list[str], today: date) -> list[NormalizedRow]:
    selected = set(selected_accounts)
    best_cash: dict[tuple[str, str], tuple[int, Any]] = {}
    for value in list(ib.accountValues() or []):
        account = _text(getattr(value, "account", ""))
        currency = _text(getattr(value, "currency", "")).upper()
        tag = _text(getattr(value, "tag", ""))
        if not account or currency in IGNORED_CASH_CURRENCIES or tag not in CASH_TAG_PRIORITY:
            continue
        if selected and account not in selected:
            continue
        key = (account, currency)
        priority = CASH_TAG_PRIORITY[tag]
        if key not in best_cash or priority < best_cash[key][0]:
            best_cash[key] = (priority, value)

    rows: list[NormalizedRow] = []
    for (account, currency), (_, value) in sorted(best_cash.items()):
        amount = _decimal(getattr(value, "value", 0))
        if amount == 0:
            continue
        tag = _text(getattr(value, "tag", ""))
        rows.append(
            NormalizedRow(
                account_name=account,
                provider="IBKR",
                date=today,
                type="cash_balance",
                instrument_code=f"{currency} CASH",
                instrument_name=f"{currency} Cash",
                isin="",
                asset_type="cash",
                quantity=amount,
                price=Decimal("1"),
                amount=amount,
                currency=currency,
                fee=Decimal("0"),
                tax=Decimal("0"),
                description=f"IBKR {tag}",
            )
        )
    return rows


def _execution_rows(ib: Any, selected_accounts: list[str], today: date) -> list[NormalizedRow]:
    selected = set(selected_accounts)
    rows: list[NormalizedRow] = []
    for fill in list(ib.reqExecutions() or []):
        execution = fill.execution
        contract = fill.contract
        account = _text(getattr(execution, "acctNumber", ""))
        if selected and account not in selected:
            continue
        quantity = _decimal(getattr(execution, "shares", 0))
        price = _decimal(getattr(execution, "price", 0))
        amount = (quantity * price).quantize(Decimal("0.01"))
        side = _text(getattr(execution, "side", "")).upper()
        executed_at = getattr(execution, "time", None)
        rows.append(
            NormalizedRow(
                account_name=account,
                provider="IBKR",
                date=executed_at.date() if hasattr(executed_at, "date") else today,
                type="buy" if side == "BOT" else "sell",
                instrument_code=_contract_code(contract),
                instrument_name=_contract_name(contract),
                isin="",
                asset_type=_asset_type_for_contract(contract),
                quantity=quantity,
                price=price,
                amount=amount,
                currency=_text(getattr(contract, "currency", "")) or "USD",
                fee=Decimal("0"),
                tax=Decimal("0"),
                description=f"IBKR execution {_text(getattr(execution, 'execId', ''))}",
            )
        )
    return rows


def _asset_type_for_contract(contract: Any) -> str:
    security_type = _security_type(contract)
    if security_type == "STK":
        return "stock"
    if security_type in {"ETF", "FUND", "MUTF"}:
        return "fund"
    if security_type in {"BOND", "BILL", "NOTE"}:
        return "bond"
    if security_type in {"CASH", "FX"}:
        return "cash"
    code = f"{_contract_code(contract)} {_contract_name(contract)}".upper()
    if any(token in code for token in ("US-T", "UST", "TREASURY", "T-BILL", "T BILL", "BOND")):
        return "bond"
    return "other"


def _contract_code(contract: Any) -> str:
    symbol = _text(getattr(contract, "symbol", ""))
    local_symbol = _text(getattr(contract, "localSymbol", ""))
    if _is_bond_like_contract(contract):
        return local_symbol or str(getattr(contract, "conId", "")) or symbol
    return symbol or local_symbol or str(getattr(contract, "conId", ""))


def _contract_name(contract: Any) -> str:
    local_symbol = _text(getattr(contract, "localSymbol", ""))
    symbol = _text(getattr(contract, "symbol", ""))
    long_name = _text(getattr(contract, "description", "")) or _text(getattr(contract, "longName", ""))
    if long_name:
        return long_name
    if _is_bond_like_contract(contract) and symbol and local_symbol:
        return f"{symbol} ({local_symbol})"
    if local_symbol and not local_symbol.startswith("IBCID"):
        return local_symbol
    if symbol:
        return symbol
    return str(getattr(contract, "conId", ""))


def _security_type(contract: Any) -> str:
    return _text(getattr(contract, "secType", "")).upper()


def _is_bond_like_contract(contract: Any) -> bool:
    security_type = _security_type(contract)
    if security_type in {"BOND", "BILL", "NOTE"}:
        return True
    code = " ".join(
        [
            _text(getattr(contract, "symbol", "")),
            _text(getattr(contract, "localSymbol", "")),
            _text(getattr(contract, "description", "")),
            _text(getattr(contract, "longName", "")),
        ]
    ).upper()
    return any(token in code for token in ("US-T", "UST", "TREASURY", "T-BILL", "T BILL", "BOND"))


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _position_cost(item: Any) -> Decimal | None:
    quantity = _decimal(getattr(item, "position", 0))
    average_cost = _optional_decimal(getattr(item, "averageCost", None))
    if average_cost is None:
        average_cost = _optional_decimal(getattr(item, "avgCost", None))
    if average_cost is None:
        return None
    return (quantity * average_cost).quantize(Decimal("0.01"))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _call_optional(target: Any, name: str) -> Any:
    method = getattr(target, name, None)
    if method is None:
        return None
    return method()

