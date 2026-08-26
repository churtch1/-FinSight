from __future__ import annotations

import hashlib
import hmac
import os
import re
import sys
import time
from urllib.parse import urlencode, urlsplit

AUTH_QUERY_TOKEN = "auth"
AUTH_QUERY_EXPIRES = "auth_exp"
WAKE_UP_LABELS = (
    "Yes, get this app back up!",
    "Get this app back up",
    "Wake up",
)


def signed_dashboard_url(base_url: str, password: str, expires_at: int) -> str:
    payload = f"lxy-finsight-auth-v1:{expires_at}".encode("utf-8")
    signature = hmac.new(password.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    query = urlencode({AUTH_QUERY_TOKEN: signature, AUTH_QUERY_EXPIRES: str(expires_at)})
    return f"{base_url.rstrip('/')}/?{query}"


def _click_streamlit_wake_up(page: object) -> bool:
    """Wake a sleeping Streamlit Community Cloud app when its interstitial appears."""
    for label in WAKE_UP_LABELS:
        candidate = page.get_by_text(label, exact=False)
        if candidate.count() and candidate.first.is_visible():
            candidate.first.click(timeout=10_000)
            page.wait_for_timeout(3_000)
            return True
    return False


def _page_state(page: object, body: str | None = None) -> str:
    """Return non-sensitive state markers for actionable Actions logs."""
    body = body if body is not None else page.locator("body").inner_text(timeout=5_000)
    markers = []
    if "访问密码" in body:
        markers.append("login_form")
    if any(label.casefold() in body.casefold() for label in WAKE_UP_LABELS):
        markers.append("sleeping_app")
    if "This app has encountered an error" in body or "应用发生错误" in body:
        markers.append("streamlit_error")
    if not body.strip():
        markers.append("empty_page")
    title = page.title() or "untitled"
    safe_title = re.sub(r"[^\w .:/-]", "", title)[:80]
    markers.append(f"title={safe_title}")
    markers.append(f"text_chars={len(body)}")
    return ",".join(markers)


def _safe_diagnostic(value: object) -> str:
    text = str(value)
    text = re.sub(r"([?&](?:auth|auth_exp)=)[^&\s]+", r"\1REDACTED", text)
    text = re.sub(r"\b[0-9a-fA-F]{32,}\b", "REDACTED", text)
    return text[:500]


def _request_path(request: object) -> str:
    parts = urlsplit(request.url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _attach_browser_diagnostics(page: object) -> None:
    def on_console(message: object) -> None:
        if message.type in {"error", "warning"}:
            print(f"browser_console_{message.type}: {_safe_diagnostic(message.text)}", flush=True)

    def on_request_failed(request: object) -> None:
        print(
            f"browser_request_failed: {_request_path(request)} error={_safe_diagnostic(request.failure)}",
            flush=True,
        )

    def on_websocket(socket: object) -> None:
        parts = urlsplit(socket.url)
        print(f"browser_websocket_opened: {parts.scheme}://{parts.netloc}{parts.path}", flush=True)
        socket.on("socketerror", lambda error: print(f"browser_websocket_error: {_safe_diagnostic(error)}", flush=True))
        socket.on("close", lambda: print("browser_websocket_closed", flush=True))

    page.on("console", on_console)
    page.on("pageerror", lambda error: print(f"browser_page_error: {_safe_diagnostic(error)}", flush=True))
    page.on("requestfailed", on_request_failed)
    page.on("websocket", on_websocket)


def _wait_for_dashboard(page: object, timeout_seconds: int = 30) -> str:
    deadline = time.monotonic() + timeout_seconds
    next_progress = time.monotonic() + 15
    latest_pattern = re.compile(r"最新估值(?:日期)?[：\s]")
    while time.monotonic() < deadline:
        _click_streamlit_wake_up(page)
        body = page.locator("body").inner_text(timeout=5_000)
        if "访问密码" in body:
            raise RuntimeError(
                "Dashboard authentication failed: the GitHub STREAMLIT_PASSWORD does not match Streamlit Cloud."
            )
        if "This app has encountered an error" in body or "应用发生错误" in body:
            raise RuntimeError("Streamlit displayed an application error before the dashboard loaded.")

        # Inspect the rendered body text directly. Streamlit reruns can leave a
        # hidden stale node before the visible dashboard, making `.first`
        # locators wait forever even though the dashboard is already present.
        match = latest_pattern.search(body)
        if match:
            line_start = body.rfind("\n", 0, match.start()) + 1
            line_end = body.find("\n", match.end())
            if line_end < 0:
                line_end = len(body)
            return body[line_start:line_end].strip()
        if time.monotonic() >= next_progress:
            print(f"snapshot_waiting: {_page_state(page, body)}", flush=True)
            next_progress = time.monotonic() + 15
        page.wait_for_timeout(2_000)
    body = page.locator("body").inner_text(timeout=5_000)
    raise RuntimeError(
        f"Dashboard did not become ready within {timeout_seconds}s (state={_page_state(page, body)})."
    )


def trigger_snapshot(base_url: str, password: str) -> str:
    from playwright.sync_api import sync_playwright

    if not password:
        raise RuntimeError("GitHub Actions secret STREAMLIT_PASSWORD is missing")

    url = signed_dashboard_url(base_url, password, int(time.time()) + 900)
    last_error = ""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _attach_browser_diagnostics(page)
        for attempt in range(2):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120_000)
                text = _wait_for_dashboard(page)
                # Give Streamlit's post-login daily sync and rerun time to settle.
                page.wait_for_timeout(15_000)
                if page.get_by_text("自动同步暂未完成", exact=False).count():
                    raise RuntimeError(page.get_by_text("自动同步暂未完成", exact=False).first.inner_text())
                browser.close()
                return text
            except Exception as exc:
                last_error = str(exc)
                print(f"snapshot_attempt_failed: attempt={attempt + 1}, error={last_error}", flush=True)
                if attempt == 0:
                    page.wait_for_timeout(5_000)
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
