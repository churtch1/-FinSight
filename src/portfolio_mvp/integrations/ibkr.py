from __future__ import annotations

from datetime import date
from decimal import Decimal

from portfolio_mvp.config import Settings, get_settings
from portfolio_mvp.models import NormalizedRow


def sync_ibkr_rows(account: str = "all", settings: Settings | None = None) -> list[NormalizedRow]:
    settings = settings or get_settings()
    try:
        from ib_insync import IB
    except ImportError as exc:
        raise RuntimeError("ib-insync is not installed. Run pip install -r requirements.txt.") from exc

    ib = IB()
    try:
        ib.connect(settings.ibkr_host, settings.ibkr_port, clientId=settings.ibkr_client_id, timeout=8)
    except Exception as exc:
        raise RuntimeError(
            f"Cannot connect to IBKR at {settings.ibkr_host}:{settings.ibkr_port}. "
            "Start IB Gateway/TWS and enable API connections."
        ) from exc

    rows: list[NormalizedRow] = []
    try:
        accounts = ib.managedAccounts()
        selected_accounts = accounts if account == "all" else [account]
        portfolio_items = ib.portfolio()
        account_values = ib.accountValues()
        today = date.today()

        for item in portfolio_items:
            if selected_accounts and item.account not in selected_accounts:
                continue
            contract = item.contract
            market_value = Decimal(str(item.marketValue or 0))
            rows.append(
                NormalizedRow(
                    account_name=item.account,
                    provider="IBKR",
                    date=today,
                    type="position_snapshot",
                    instrument_code=contract.symbol or str(contract.conId),
                    instrument_name=contract.localSymbol or contract.symbol or str(contract.conId),
                    isin="",
                    asset_type="stock" if contract.secType == "STK" else "fund" if contract.secType in {"ETF", "FUND"} else "other",
                    quantity=Decimal(str(item.position or 0)),
                    price=Decimal(str(item.marketPrice or 0)),
                    amount=market_value,
                    currency=item.contract.currency or "USD",
                    fee=Decimal("0"),
                    tax=Decimal("0"),
                    description="IBKR portfolio snapshot",
                )
            )

        for value in account_values:
            if selected_accounts and value.account not in selected_accounts:
                continue
            if value.tag in {"CashBalance", "TotalCashBalance"} and value.currency == "USD":
                amount = Decimal(str(value.value or "0"))
                rows.append(
                    NormalizedRow(
                        account_name=value.account,
                        provider="IBKR",
                        date=today,
                        type="cash_balance",
                        instrument_code="USD CASH",
                        instrument_name="USD Cash",
                        isin="",
                        asset_type="cash",
                        quantity=amount,
                        price=Decimal("1"),
                        amount=amount,
                        currency="USD",
                        fee=Decimal("0"),
                        tax=Decimal("0"),
                        description=f"IBKR {value.tag}",
                    )
                )

        # TWS executions are session/range dependent. This captures what Gateway/TWS
        # currently exposes without making the MVP rely on complete history.
        for execution in ib.reqExecutions():
            exec_detail = execution.execution
            contract = execution.contract
            if selected_accounts and exec_detail.acctNumber not in selected_accounts:
                continue
            qty = Decimal(str(exec_detail.shares or 0))
            price = Decimal(str(exec_detail.price or 0))
            amount = (qty * price).quantize(Decimal("0.01"))
            rows.append(
                NormalizedRow(
                    account_name=exec_detail.acctNumber,
                    provider="IBKR",
                    date=exec_detail.time.date() if hasattr(exec_detail.time, "date") else today,
                    type="buy" if exec_detail.side.upper() == "BOT" else "sell",
                    instrument_code=contract.symbol or str(contract.conId),
                    instrument_name=contract.localSymbol or contract.symbol or str(contract.conId),
                    isin="",
                    asset_type="stock" if contract.secType == "STK" else "other",
                    quantity=qty,
                    price=price,
                    amount=amount,
                    currency=contract.currency or "USD",
                    fee=Decimal("0"),
                    tax=Decimal("0"),
                    description=f"IBKR execution {exec_detail.execId}",
                )
            )
        return rows
    finally:
        ib.disconnect()

