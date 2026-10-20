"""build_game：纪要解析与每周出题。纯函数，不碰行情和回测目录。"""
from __future__ import annotations

from build_game import WHY_MAX, parse_transcript, pick_turns

MEMO = """# Committee: QQQ

**Date**: 2026-08-13
**Verdict**: ACCUMULATE (confidence 0.62)

## CIO Memo (Round 3)

综合三方意见，本轮回测给出评级。

【结论】三方信号偏多：**量化**看多、宏观温和。

【操作纪律】若已持仓，继续持有。

## Macro Strategist (shared)
ONE_LINER: 不该被取到
"""


def test_parse_takes_verdict_confidence_and_conclusion():
    assert parse_transcript(MEMO) == ("ACCUMULATE", "三方信号偏多：量化看多、宏观温和。")


def test_parse_falls_back_to_first_line_and_truncates():
    v, why = parse_transcript(MEMO.replace("【结论】", "").replace("综合三方意见，本轮回测给出评级。", "长" * 200))
    assert v == "ACCUMULATE"
    assert why.endswith("…") and len(why) == WHY_MAX + 1


def test_parse_text_mode_memo_gives_no_reason():
    text = MEMO.replace("综合三方意见，本轮回测给出评级。\n\n【结论】三方信号偏多：**量化**看多、宏观温和。", "VERDICT: ACCUMULATE\nCONFIDENCE: 0.62\nPERSONAL_NOTE:\n  - 回测模式假设持仓中性")
    assert parse_transcript(text) == ("ACCUMULATE", "")


def test_parse_without_verdict_returns_nothing():
    assert parse_transcript("# Committee: QQQ\n\nno verdict here") == (None, "")


def test_one_turn_per_week_first_decided_day_and_last_day_only_settles():
    days = ["2025-12-30", "2026-01-05", "2026-01-06", "2026-01-12", "2026-01-13", "2026-01-19"]
    decisions = {"2026-01-06": ("HOLD", "a"), "2026-01-12": ("TRIM", "b")}
    turns = pick_turns(days, decisions, "2026-01-01")
    assert [(days[t["i"]], t["v"]) for t in turns] == [("2026-01-06", "HOLD"), ("2026-01-12", "TRIM")]


def test_week_without_decision_uses_first_trading_day_as_hold():
    days = ["2026-01-05", "2026-01-06", "2026-01-12"]
    turns = pick_turns(days, {}, "2026-01-01")
    assert turns == [{"i": 0, "v": None, "why": ""}]
