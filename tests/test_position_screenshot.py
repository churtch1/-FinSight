from __future__ import annotations

import json
from io import BytesIO

from PIL import Image

import pytest

from portfolio_mvp.config import Settings
from portfolio_mvp.parsers.position_screenshot import (
    MissingScreenshotRecognitionConfig,
    _recognition_prompt,
    _textual_source_override,
    _visual_source_override,
    _normalize_record,
    recognize_position_screenshot_records,
)


class FakeResponse:
    status_code = 200

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "positions": [
                                    {
                                        "instrument_code": "270023",
                                        "instrument_name": "GF Global Select",
                                        "asset_type": "fund",
                                        "quantity": "",
                                        "price": "",
                                        "fund_nav": "2.3456",
                                        "fund_nav_date": "2026-05-11",
                                        "amount": "2,345.60",
                                        "currency": "",
                                        "cost": "2,000.00",
                                        "unrealized_pnl": "",
                                        "total_pnl": "345.60",
                                        "pnl_pct": "17.28%",
                                        "description": "Alipay screenshot",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }


def test_recognize_position_screenshot_records_calls_bailian_and_normalizes(monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("portfolio_mvp.parsers.position_screenshot.requests.post", fake_post)
    settings = Settings(dashscope_api_key="test-key", dashscope_ocr_model="test-model", dashscope_portfolio_model="")

    rows = recognize_position_screenshot_records(
        b"fake-image",
        mime_type="image/png",
        source_label="Alipay",
        settings=settings,
    )

    assert captured["url"] == settings.dashscope_compatible_api_url
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "test-model"
    assert captured["json"]["messages"][0]["content"][0]["type"] == "image_url"
    assert captured["json"]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert rows[0]["instrument_code"] == "270023"
    assert rows[0]["currency"] == "CNY"
    assert rows[0]["asset_type"] == "fund"


def test_recognize_position_screenshot_records_requires_dashscope_key(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(MissingScreenshotRecognitionConfig):
        recognize_position_screenshot_records(
            b"fake-image",
            mime_type="image/png",
            source_label="CMB",
            settings=Settings(dashscope_api_key=""),
        )


def test_normalize_record_preserves_usd_wealth_product_currency() -> None:
    row = _normalize_record(
        {
            "instrument_code": "CMB-USD-001",
            "instrument_name": "招商银行美元理财产品",
            "asset_type": "other",
            "quantity": "1",
            "price": "",
            "fund_nav": "",
            "fund_nav_date": "",
            "amount": "10,000.00",
            "currency": "CNY",
            "cost": "9,900.00",
            "unrealized_pnl": "100.00",
            "total_pnl": "100.00",
            "pnl_pct": "",
            "description": "美元持仓 USD",
        }
    )

    assert row["asset_type"] == "wealth_product"
    assert row["currency"] == "USD"


def test_recognition_prompt_tells_model_to_ignore_yesterday_return_for_fund_pnl() -> None:
    prompt = _recognition_prompt("CMB")

    assert "yesterday return" in prompt
    assert "amount/yesterday return" in prompt
    assert "larger/top number in that column is amount" in prompt
    assert "smaller/bottom number is yesterday return" in prompt
    assert "holding return/rate" in prompt
    assert "Do not use yesterday return" in prompt
    assert "holding return/rate 4,583.66 and +27.12%" in prompt
    assert "total_pnl=4583.66" in prompt
    assert "ignore 68.83" in prompt


def test_recognition_prompt_covers_alipay_combined_amount_yesterday_return_column() -> None:
    prompt = _recognition_prompt("Alipay")

    assert "34,960.77 above +409.74" in prompt
    assert "holding return/rate +14,960.77 above +74.80%" in prompt
    assert "amount=34960.77" in prompt
    assert "total_pnl=14960.77" in prompt
    assert "pnl_pct=74.80%" in prompt
    assert "ignore +409.74" in prompt


def test_visual_source_override_uses_blue_alipay_and_white_cmb_convention() -> None:
    def image_bytes(color: str) -> bytes:
        image = Image.new("RGB", (100, 100), color=color)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    assert _visual_source_override(image_bytes("#1976D2")) == "支付宝"
    assert _visual_source_override(image_bytes("#FFFFFF")) == "招商银行"


def test_textual_source_override_prioritizes_visible_cmb_branding() -> None:
    assert _textual_source_override([{"instrument_name": "招行黄金账户", "description": ""}]) == "招商银行"
