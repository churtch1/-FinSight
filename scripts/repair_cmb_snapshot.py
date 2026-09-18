from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal

from portfolio_mvp.config import get_settings
from portfolio_mvp.db import _select_all, get_supabase
from portfolio_mvp.fund_nav import AutomaticFundNavProvider, normalize_fund_code
from portfolio_mvp.fx import FxRate, convert_to_usd, fetch_online_usd_rates, latest_rate_from_rows
from portfolio_mvp.repository import upsert_fund_navs


POSITION_COLUMNS = (
    "account_id,instrument_id,quantity,price_original,market_value_original,currency,"
    "market_value_usd,fx_rate_to_usd,fx_rate_source,fx_rate_date,valuation_date,"
    "cost_original,unrealized_pnl_original,income_original,total_pnl_original,pnl_pct,"
    "quantity_source,estimate_note,accounts(account_name,provider),"
    "instruments(symbol,name,asset_type)"
)


def _payload(row: dict, target_date: date) -> dict:
    allowed = {
        "account_id", "instrument_id", "quantity", "price_original", "market_value_original",
        "currency", "market_value_usd", "fx_rate_to_usd", "fx_rate_source", "fx_rate_date",
        "cost_original", "unrealized_pnl_original", "income_original", "total_pnl_original",
        "pnl_pct", "quantity_source", "estimate_note",
    }
    result = {key: value for key, value in row.items() if key in allowed}
    result["valuation_date"] = target_date.isoformat()
    return result


def build_repair(client) -> tuple[date, list[dict], list]:
    rows = _select_all(
        client,
        "positions_current",
        POSITION_COLUMNS,
        order_by=(("valuation_date", False), ("id", False)),
    )
    cmb_rows = [
        row for row in rows
        if (row.get("accounts") or {}).get("provider") == "CMB"
        and (row.get("accounts") or {}).get("account_name") == "招商银行"
    ]
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in cmb_rows:
        by_date[str(row.get("valuation_date") or "")].append(row)
    if not by_date:
        raise RuntimeError("No CMB account snapshots found.")

    # The absolute largest snapshot briefly contained both the retired USD
    # 10,543.76 product and its USD 561 replacement.  Use the newest snapshot
    # with the user-confirmed 10 funds + 3 wealth products instead.
    complete_candidates = [item for item in by_date.items() if len(item[1]) >= 13]
    if not complete_candidates:
        raise RuntimeError("No complete 13-position CMB snapshot found.")
    baseline_date, baseline = max(complete_candidates, key=lambda item: item[0])
    fund_codes = sorted(
        {
            normalize_fund_code(str((row.get("instruments") or {}).get("symbol") or ""))
            for row in baseline
            if (row.get("instruments") or {}).get("asset_type") == "fund"
        }
        - {""}
    )
    navs = list(AutomaticFundNavProvider(settings=get_settings()).fetch_many(fund_codes).values())
    valid_navs = {nav.fund_code: nav for nav in navs if nav.status == "ok" and nav.unit_nav > 0}
    if set(valid_navs) != set(fund_codes):
        missing = sorted(set(fund_codes) - set(valid_navs))
        raise RuntimeError(f"Missing current NAV for: {', '.join(missing)}")
    target_date = max(nav.nav_date for nav in valid_navs.values())

    existing = {
        str(row.get("instrument_id"))
        for row in by_date.get(target_date.isoformat(), [])
    }
    fx_rows = client.table("fx_rates").select("*").order("rate_date", desc=True).execute().data or []
    cny_rate = latest_rate_from_rows("CNY", fx_rows)
    if cny_rate is None:
        cny_rate = fetch_online_usd_rates().get("CNY")
    if cny_rate is None:
        raise RuntimeError("No CNY to USD rate available.")

    payloads: list[dict] = []
    for row in baseline:
        if str(row.get("instrument_id")) in existing:
            continue
        payload = _payload(row, target_date)
        instrument = row.get("instruments") or {}
        asset_type = str(instrument.get("asset_type") or "")
        symbol = str(instrument.get("symbol") or "")
        if asset_type == "fund":
            nav = valid_navs[normalize_fund_code(symbol)]
            quantity = Decimal(str(row.get("quantity") or "0"))
            market_value = (quantity * nav.unit_nav).quantize(Decimal("0.01"))
            payload.update(
                {
                    "price_original": str(nav.unit_nav),
                    "market_value_original": str(market_value),
                    "market_value_usd": str(convert_to_usd(market_value, "CNY", cny_rate)),
                    "fx_rate_to_usd": str(cny_rate.rate),
                    "fx_rate_source": f"snapshot_repair:{nav.source}",
                    "fx_rate_date": nav.nav_date.isoformat(),
                    "estimate_note": f"Restored from complete {baseline_date} snapshot; NAV {nav.nav_date.isoformat()}.",
                }
            )
            cost = row.get("cost_original")
            if cost is not None:
                cost_value = Decimal(str(cost))
                pnl = (market_value - cost_value).quantize(Decimal("0.01"))
                payload["unrealized_pnl_original"] = str(pnl)
                payload["total_pnl_original"] = str(pnl)
                payload["pnl_pct"] = str((pnl / cost_value).quantize(Decimal("0.000001"))) if cost_value else None
        else:
            currency = str(row.get("currency") or "").upper()
            value = Decimal(str(row.get("market_value_original") or "0"))
            rate = FxRate("USD", "USD", Decimal("1"), target_date, "identity") if currency == "USD" else cny_rate
            payload["market_value_usd"] = str(convert_to_usd(value, currency, rate))
            payload["fx_rate_to_usd"] = str(rate.rate)
            payload["fx_rate_source"] = "snapshot_repair:carried_forward"
            payload["fx_rate_date"] = target_date.isoformat()
            payload["estimate_note"] = f"Carried forward from complete {baseline_date} snapshot."
        payloads.append(payload)
    return target_date, payloads, navs


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore the complete CMB account snapshot.")
    parser.add_argument("--apply", action="store_true", help="Write the repair to Supabase.")
    args = parser.parse_args()
    settings = get_settings()
    client = get_supabase(use_service_role=args.apply, settings=settings)
    target_date, payloads, navs = build_repair(client)
    print(f"target_date={target_date} missing_rows={len(payloads)}")
    for payload in payloads:
        print(payload["instrument_id"], payload.get("market_value_original"), payload.get("estimate_note"))
    if not args.apply:
        print("Dry run only. Re-run with --apply to write these rows.")
        return
    upsert_fund_navs(client, navs)
    if payloads:
        client.table("positions_current").upsert(
            payloads,
            on_conflict="account_id,instrument_id,valuation_date",
        ).execute()
    print(f"Applied {len(payloads)} restored rows.")


if __name__ == "__main__":
    main()
