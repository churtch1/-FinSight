from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from typing import Any

import requests
from PIL import Image

from portfolio_mvp.config import Settings, get_settings


POSITION_SCREENSHOT_COLUMNS: tuple[str, ...] = (
    "instrument_code",
    "instrument_name",
    "asset_type",
    "quantity",
    "price",
    "fund_nav",
    "fund_nav_date",
    "amount",
    "currency",
    "cost",
    "unrealized_pnl",
    "total_pnl",
    "pnl_pct",
    "description",
)

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
USD_MARKERS = ("USD", "US$", "$", "\u7f8e\u5143", "\u7f8e\u91d1")
HKD_MARKERS = ("HKD", "HK$", "\u6e2f\u5e01", "\u6e2f\u5143")
CNY_MARKERS = ("CNY", "RMB", "\u4eba\u6c11\u5e01", "\u5143", "\uffe5", "\u00a5")
WEALTH_MARKERS = (
    "\u7406\u8d22",
    "\u5b58\u6b3e",
    "\u7ed3\u6784\u6027",
    "\u7968\u636e",
    "\u4fe1\u6258",
    "QDII",
    "WEALTH",
    "STRUCTURED",
    "DEPOSIT",
)


class MissingScreenshotRecognitionConfig(RuntimeError):
    pass


def recognize_position_screenshot_records(
    image_bytes: bytes,
    *,
    mime_type: str,
    source_label: str,
    settings: Settings | None = None,
) -> list[dict[str, str]]:
    _, records = recognize_position_screenshot_with_source(
        image_bytes, mime_type=mime_type, source_label=source_label, settings=settings
    )
    return records


def recognize_position_screenshot_with_source(
    image_bytes: bytes,
    *,
    mime_type: str,
    source_label: str = "unknown",
    settings: Settings | None = None,
) -> tuple[str, list[dict[str, str]]]:
    settings = settings or get_settings()
    api_key = getattr(settings, "dashscope_api_key", "") or os.getenv("DASHSCOPE_API_KEY", "")
    api_url = getattr(settings, "dashscope_compatible_api_url", "") or os.getenv(
        "DASHSCOPE_COMPATIBLE_API_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    model = getattr(settings, "dashscope_ocr_model", "") or os.getenv("DASHSCOPE_OCR_MODEL", "qwen-vl-ocr-latest")
    if not api_key:
        raise MissingScreenshotRecognitionConfig("Set DASHSCOPE_API_KEY to enable screenshot recognition.")
    if mime_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError("Screenshot format must be PNG, JPG/JPEG, or WEBP.")
    if not image_bytes:
        raise ValueError("Screenshot file is empty.")

    response = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=_build_request_payload(
            image_bytes,
            mime_type,
            source_label,
            model,
            use_ocr_pixel_limits="ocr" in model.casefold(),
            high_resolution="ocr" not in model.casefold(),
        ),
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Screenshot recognition failed: Bailian API returned HTTP {response.status_code}.")

    payload = response.json()
    output_text = _extract_chat_completion_text(payload)
    try:
        parsed = json.loads(_strip_json_markdown(output_text))
    except json.JSONDecodeError as exc:
        raise ValueError("Screenshot recognition result is not valid JSON.") from exc

    review_model = getattr(settings, "dashscope_portfolio_model", "")
    if review_model and review_model != model:
        review_response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=_build_request_payload(
                image_bytes,
                mime_type,
                source_label,
                review_model,
                prompt=_portfolio_review_prompt(parsed),
                use_ocr_pixel_limits=False,
                high_resolution=True,
            ),
            timeout=90,
        )
        if review_response.status_code < 400:
            try:
                parsed = json.loads(_strip_json_markdown(_extract_chat_completion_text(review_response.json())))
            except json.JSONDecodeError:
                # Keep a usable OCR result when a reviewer response is malformed.
                pass

    positions = parsed.get("positions")
    if not isinstance(positions, list):
        raise ValueError("Screenshot recognition result is missing positions.")
    records = [_normalize_record(item) for item in positions if isinstance(item, dict)]
    detected_source = (
        _textual_source_override(records)
        or _visual_source_override(image_bytes)
        or str(parsed.get("source") or source_label or "unknown").strip()
    )
    return detected_source, records


def _build_request_payload(
    image_bytes: bytes,
    mime_type: str,
    source_label: str,
    model: str,
    prompt: str | None = None,
    use_ocr_pixel_limits: bool = True,
    high_resolution: bool = False,
) -> dict[str, Any]:
    image_data = base64.b64encode(image_bytes).decode("ascii")
    image_content: dict[str, Any] = {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
    }
    if use_ocr_pixel_limits:
        image_content.update({"min_pixels": 3072, "max_pixels": 8388608})
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    image_content,
                    {
                        "type": "text",
                        "text": prompt or _recognition_prompt(source_label),
                    },
                ],
            }
        ],
        "max_tokens": 4096,
    }
    if high_resolution:
        payload["vl_high_resolution_images"] = True
    return payload


def _recognition_prompt(source_label: str) -> str:
    columns = ", ".join(POSITION_SCREENSHOT_COLUMNS)
    return (
        f"You are extracting portfolio holdings from a {source_label} asset screenshot.\n"
        "Only extract individual holdings that are clearly visible in the screenshot. Do not invent data.\n\n"
        "Return JSON only, with this exact top-level shape:\n"
        f'{{"source":"招商银行|支付宝|unknown","positions":[{{"{POSITION_SCREENSHOT_COLUMNS[0]}":"","instrument_name":"","asset_type":"","quantity":"","price":"","fund_nav":"","fund_nav_date":"","amount":"","currency":"","cost":"","unrealized_pnl":"","total_pnl":"","pnl_pct":"","description":""}}]}}\n\n'
        f"Required fields for every position: {columns}.\n"
        "Set source to 招商银行 or 支付宝 only when the app branding or account context is clearly visible; otherwise use unknown.\n"
        "Source rules: 招商银行, 招行, CMB, China Merchants Bank, or the red CMB logo means source=招商银行. 支付宝, 蚂蚁财富, Ant Group, or Alipay logo means source=支付宝. Never infer 支付宝 merely because a page shows funds; when source evidence is absent use unknown.\n"
        "Field notes:\n"
        "- asset_type must be one of: stock, fund, wealth_product, bond, cash, gold, crypto, other.\n"
        "- amount is the current market value or holding amount in the holding's own currency.\n"
        "- quantity is fund shares, product units, stock shares, or gold grams.\n"
        "- price is unit price or unit NAV.\n"
        "- fund_nav is fund unit NAV when shown.\n"
        "- fund_nav_date must use YYYY-MM-DD when shown.\n"
        "- pnl_pct may keep a percent sign.\n"
        "- currency must preserve the screenshot currency. Use USD for USD, US dollar, dollar sign, mei yuan, or mei jin. Use CNY for RMB, renminbi, yuan, or CNY. Use HKD for HKD or Hong Kong dollar. Default to CNY only when no currency is shown.\n"
        "- description can include account/page/product context from the screenshot.\n\n"
        "Important currency rules:\n"
        "- Do not convert values between currencies.\n"
        "- For USD wealth management products, keep amount, cost, unrealized_pnl, total_pnl, and price in USD and set currency to USD.\n"
        "- If the screenshot shows both original-currency value and converted RMB reference value, use the original holding currency amount. Put the converted RMB reference in description if useful.\n"
        "- For CMB screenshots, Chinese words meaning USD include mei yuan and mei jin. Treat those as USD.\n"
        "- For wealth management pages with product names containing Chinese words for wealth management, deposit, structured product, note, trust, or QDII, set asset_type to wealth_product unless it is clearly a fund.\n\n"
        "Important CMB gold rules:\n"
        "- Screens titled with Chinese words meaning gold, CMB gold account, physical gold, target gold saving, or CMB gold yield are gold holdings.\n"
        "- For gold pages, create one holding row even if the page is a summary card.\n"
        "- Use the field meaning holding amount in CNY as amount.\n"
        "- Use the field meaning holding grams as quantity.\n"
        "- Set asset_type to gold and currency to CNY.\n"
        "- If current/reference gold price is not shown, leave price empty so it can be calculated as amount / quantity.\n"
        "- Use holding profit as unrealized_pnl and total_pnl for current holding PnL.\n"
        "- Do not use accumulated profit to calculate current holding cost when holding profit is present; put accumulated profit in description instead.\n\n"
        "Important fund rules:\n"
        "- If a fund row has fund code and current amount but no shares, leave quantity empty.\n"
        "- Put latest unit NAV shown on the screenshot in fund_nav. If NAV is not shown, leave fund_nav empty.\n"
        "- The app can infer fund shares later from amount / latest disclosed NAV.\n\n"
        "Important CMB/Alipay fund holding-list rules:\n"
        "- Some holding lists show three columns like amount, yesterday return, and holding return/rate.\n"
        "- If a column header combines amount/yesterday return, the larger/top number in that column is amount and the smaller/bottom number is yesterday return.\n"
        "- Never leave amount empty when the top number is visible in an amount/yesterday return column.\n"
        "- If a column header combines holding return/rate, the upper amount in that column is total holding PnL and the lower percent is pnl_pct.\n"
        "- Do not use yesterday return, yesterday income, or daily profit as unrealized_pnl, total_pnl, cost, or pnl_pct.\n"
        "- Use only the values under holding return/rate, holding profit/rate, position return/rate, or total holding gain/rate for current PnL fields.\n"
        "- In a row like amount 21,483.66, yesterday return 68.83, holding return/rate 4,583.66 and +27.12%, set amount=21483.66, total_pnl=4583.66, unrealized_pnl=4583.66, pnl_pct=27.12%, and ignore 68.83 except optionally in description.\n\n"
        "- In an Alipay row with header amount/yesterday return and values 34,960.77 above +409.74, plus holding return/rate +14,960.77 above +74.80%, set amount=34960.77, total_pnl=14960.77, unrealized_pnl=14960.77, pnl_pct=74.80%, and ignore +409.74 except optionally in description.\n\n"
        'If the screenshot only shows total assets and no individual holdings, return {"positions":[]}.\n'
        "Numbers should not include currency symbols. Commas and minus signs are allowed."
    )


def _portfolio_review_prompt(ocr_draft: dict[str, Any]) -> str:
    return (
        "You are the final reviewer for a Chinese personal portfolio screenshot. Inspect the ORIGINAL image, "
        "then correct the OCR draft below. Return JSON only in the exact schema required below.\n\n"
        + _recognition_prompt("unknown")
        + "\n\nOCR draft (it can be wrong or incomplete):\n"
        + json.dumps(ocr_draft, ensure_ascii=False)
        + "\n\nFinal-review priorities:\n"
        "- Source must be decided from visible app/bank branding, never from a guessed product type.\n"
        "- For each visible fund row, recover total_pnl and pnl_pct from the holding-return column when present.\n"
        "- Treat 当日收益, 昨日收益, 日收益, and daily P/L as separate daily figures; never write them into unrealized_pnl, total_pnl, cost, or pnl_pct.\n"
        "- If cumulative holding P/L is shown, set both unrealized_pnl and total_pnl to it.\n"
        "- Do not invent a P/L or percentage that is not visible."
    )


def _visual_source_override(image_bytes: bytes) -> str:
    """Apply the user's stable UI convention before accepting an LLM source guess.

    The user's Alipay holding captures use a large blue page background, while
    China Merchants Bank captures are predominantly white.  This signal is more
    dependable than inferring the provider from fund names or values.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            pixels = image.convert("RGB").resize((80, 80)).getdata()
    except Exception:
        return ""

    total = len(pixels)
    if not total:
        return ""
    blue = sum(1 for red, green, blue_value in pixels if blue_value >= 130 and blue_value > red * 1.18 and blue_value > green * 1.05)
    white = sum(1 for red, green, blue_value in pixels if min(red, green, blue_value) >= 238 and max(red, green, blue_value) - min(red, green, blue_value) <= 18)
    if blue / total >= 0.12:
        return "支付宝"
    if white / total >= 0.58:
        return "招商银行"
    return ""


def _textual_source_override(records: list[dict[str, str]]) -> str:
    """Provider names visible in the screenshot outrank a model classification."""
    text = " ".join(" ".join(str(value) for value in record.values()) for record in records).casefold()
    if any(marker in text for marker in ("招商银行", "招行", "cmb", "china merchants bank")):
        return "招商银行"
    if any(marker in text for marker in ("支付宝", "蚂蚁财富", "alipay", "ant group")):
        return "支付宝"
    return ""


def _extract_chat_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Screenshot recognition returned no choices.")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("Screenshot recognition result has invalid choice format.")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("Screenshot recognition result is missing message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Screenshot recognition returned no text.")
    return content


def _strip_json_markdown(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _normalize_record(raw: dict[str, Any]) -> dict[str, str]:
    record = {column: _clean_text(raw.get(column)) for column in POSITION_SCREENSHOT_COLUMNS}
    joined_text = " ".join(record.values())
    record["asset_type"] = _normalize_screenshot_asset_type(record["asset_type"], joined_text)
    record["currency"] = _normalize_screenshot_currency(record["currency"], joined_text)
    return record


def _normalize_screenshot_currency(raw_currency: str, joined_text: str) -> str:
    text = f"{raw_currency} {joined_text}".upper()
    if _contains_any(text, USD_MARKERS):
        return "USD"
    if _contains_any(text, HKD_MARKERS):
        return "HKD"
    if _contains_any(text, CNY_MARKERS):
        return "CNY"
    return (raw_currency or "CNY").upper()


def _normalize_screenshot_asset_type(raw_asset_type: str, joined_text: str) -> str:
    asset_type = (raw_asset_type or "").strip().lower() or "other"
    if asset_type in {"fund", "gold", "wealth_product", "stock", "bond", "cash", "crypto", "other"}:
        if asset_type == "other" and _contains_any(joined_text.upper(), WEALTH_MARKERS):
            return "wealth_product"
        return asset_type
    if _contains_any(joined_text.upper(), WEALTH_MARKERS):
        return "wealth_product"
    return "other"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.upper() in text for marker in markers)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
