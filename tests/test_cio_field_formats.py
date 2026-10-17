"""CIO memo 字段解析容忍 LLM 的常见写法：货币符号、千分位、正负号、markdown 加粗、句末句号。

旧正则 SUGGESTED_ALLOC_xxx: (-?\\d+) 把 10,000 读成 10、¥800 读成 0（存档里有 3 次带 ¥ 的金额被记成 0）；
CONFIDENCE 的 [\\d.]+ 把 "0.72." 的句号吃进去，float 抛错整轮作废；JSON 路径的字符串金额同样被读成 0。
"""
from __future__ import annotations

import pytest

from openinvest.core.committee import parse_cio_memo
from openinvest.core.config import reset_config


@pytest.fixture(autouse=True)
def _reset_config():
    reset_config()
    yield
    reset_config()


def _memo(alloc: str) -> str:
    return f"VERDICT: ACCUMULATE\nCONFIDENCE: 0.6\nDOMINANT_VIEW: quant\nSUGGESTED_ALLOC_CNY: {alloc}\n"


@pytest.mark.parametrize("raw,expected", [
    ("5000", 5000), ("10,000", 10000), ("¥800", 800), ("¥5,000", 5000), ("-3,000", -3000),
    ("-¥78,000", -78000), ("¥-3000", -3000), ("+5000", 5000), ("**5000**", 5000),
    ("−2000", -2000), ("5000 元", 5000), ("0", 0), ("N/A", 0),
])
def test_alloc_text_formats(raw, expected):
    assert parse_cio_memo(_memo(raw))["alloc_cny"] == expected


@pytest.mark.parametrize("raw,expected", [
    (5000, 5000), (5000.9, 5000), ("5,000", 5000), ("¥-3,000", -3000), (None, 0), ("N/A", 0),
    (float("nan"), 0), (float("inf"), 0),
])
def test_alloc_json_values(raw, expected):
    fields = {"verdict": "HOLD", "confidence": 0.5, "dominant_view": "macro", "suggested_alloc_cny": raw}
    assert parse_cio_memo("(json)", fields=fields)["alloc_cny"] == expected


def test_confidence_trailing_period_parses():
    r = parse_cio_memo("VERDICT: HOLD\nCONFIDENCE: 0.72.\nDOMINANT_VIEW: risk\nSUGGESTED_ALLOC_CNY: 0")
    assert r["confidence"] == 0.72


def test_markdown_bold_fields():
    r = parse_cio_memo(
        "**VERDICT**: **ACCUMULATE**\n**CONFIDENCE:** 0.6\nDOMINANT_VIEW: **quant**\n"
        "**SUGGESTED_ALLOC_CNY**: **¥5,000**\n"
    )
    assert (r["verdict"], r["confidence"], r["dominant_view"], r["alloc_cny"]) == (
        "ACCUMULATE", 0.6, "quant", 5000)
