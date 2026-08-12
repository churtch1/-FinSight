from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
from urllib.parse import urlencode

AUTH_QUERY_TOKEN = "auth"
AUTH_QUERY_EXPIRES = "auth_exp"


def signed_dashboard_url(base_url: str, password: str, expires_at: int) -> str:
    payload = f"lxy-finsight-auth-v1:{expires_at}".encode("utf-8")
    signature = hmac.new(password.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    query = urlencode({AUTH_QUERY_TOKEN: signature, AUTH_QUERY_EXPIRES: str(expires_at)})
    return f"{base_url.rstrip('/')}/?{query}"


def trigger_snapshot(base_url: str, password: str) -> str:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    if not password:
        raise RuntimeError("GitHub Actions secret STREAMLIT_PASSWORD is missing")

    url = signed_dashboard_url(base_url, password, int(time.time()) + 900)
    last_error = ""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        for attempt in range(2):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                latest = page.get_by_text("最新估值日期：", exact=False)
                latest.wait_for(state="visible", timeout=180_000)
                text = latest.first.inner_text(timeout=10_000).strip()
                # Give Streamlit's post-login daily sync and rerun time to settle.
                page.wait_for_timeout(15_000)
                if page.get_by_text("自动同步暂未完成", exact=False).count():
                    raise RuntimeError(page.get_by_text("自动同步暂未完成", exact=False).first.inner_text())
                browser.close()
                return text
            except (PlaywrightTimeoutError, RuntimeError) as exc:
                last_error = str(exc)
                if attempt == 0:
                    page.wait_for_timeout(15_000)
                    page.reload(wait_until="domcontentloaded", timeout=120_000)
        browser.close()
    raise RuntimeError(f"Dashboard snapshot did not complete after one retry: {last_error}")


def main() -> int:
    try:
        result = trigger_snapshot(
            os.environ.get("DASHBOARD_URL", "https://churtch2.streamlit.app/"),
            os.environ.get("STREAMLIT_PASSWORD", ""),
        )
    except Exception as exc:
        print(f"snapshot_failed: {exc}", file=sys.stderr)
        return 1
    print(f"snapshot_completed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
