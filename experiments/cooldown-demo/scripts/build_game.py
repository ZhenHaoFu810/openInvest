"""生成「试玩：你 vs AI」的静态数据 data/game_data.json（行情 + 委员会每周决定）。

AI 一方 = 回测舰队在 memory/.backtest/<日>/<标的>.md 里留下的委员会决定：每个决定只喂当天之前的
行情，模型训练截止早于 2026 年（ADR-022），跟实盘用的是同一套委员会。每周取第一个有决定的交易日；
那一周没有决定就记 None（页面上当作"持有"）。CIO 备忘录里的【结论】一句作为理由。

跑（从仓库根，读生产数据目录）：
    INVEST_HOME=<生产 checkout> uv run python experiments/cooldown-demo/scripts/build_game.py
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ASSETS = [  # (页面 key, 显示名, yfinance 代码)
    ("gold", "黄金", "GC=F"),
    ("ndx", "纳指100", "QQQ"),
    ("csi300", "沪深300", "510300.SS"),
    ("tencent", "腾讯控股", "0700.HK"),
]
CHART_FROM = "2025-10-01"   # 图上第一周前留一个季度的走势当背景
GAME_FROM = "2026-01-01"
GAME_TO = "2026-09-30"     # 停在上个季度末：最近几周的决定离"现在"太近，像当下建议（细则 4.9）
WHY_MAX = 80
OUT = Path(__file__).resolve().parent.parent / "data" / "game_data.json"

_VERDICT_RE = re.compile(r"^\*\*Verdict\*\*:\s*([A-Z]+)", re.M)
_KV_RE = re.compile(r"^[A-Z_]{3,}:")
_CIO_RE = re.compile(r"^## CIO Memo[^\n]*\n(.*?)(?=^## |\Z)", re.S | re.M)


def parse_transcript(text: str) -> Tuple[Optional[str], str]:
    """委员会纪要 → (裁决, 理由)。置信度不要：比赛版对外不给置信度。理由取 CIO 备忘录的【结论】句，没有就取第一句。"""
    m = _VERDICT_RE.search(text)
    if not m:
        return None, ""
    verdict = m.group(1)
    memo = _CIO_RE.search(text)
    why = ""
    if memo:
        lines = [ln.strip() for ln in memo.group(1).splitlines() if ln.strip() and not ln.startswith("```")]
        # 文本模式的备忘录是 VERDICT:/CONFIDENCE:/... 键值块，没有散文理由——那就不给理由，别把键值行当理由
        prose = list(itertools.takewhile(lambda ln: not _KV_RE.match(ln), lines))
        hit = next((ln for ln in lines if ln.startswith("【结论】")), None) or (prose[0] if prose else "")
        why = re.sub(r"[*#`>]", "", hit.removeprefix("【结论】")).strip()
        if len(why) > WHY_MAX:
            why = why[:WHY_MAX].rstrip("，、；,; ") + "…"
    return verdict, why


def pick_turns(days: List[str], decisions: Dict[str, Tuple[str, str]], start: str) -> List[Dict[str, Any]]:
    """每个自然周一个决策点：该周第一个有决定的交易日，没有就用该周第一个交易日（v=None）。
    最后一个交易日只用来结算，不再出题。days 为升序交易日（含 start 之前的背景段）。"""
    weeks: Dict[Tuple[int, int], List[int]] = {}
    for i, d in enumerate(days[:-1]):
        if d >= start:
            weeks.setdefault(date.fromisoformat(d).isocalendar()[:2], []).append(i)
    turns = []
    for idx in weeks.values():
        i = next((j for j in idx if days[j] in decisions), idx[0])
        v, why = decisions.get(days[i], (None, ""))
        turns.append({"i": i, "v": v, "why": why})
    return turns


def _safe(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", symbol)


def build(root: Path) -> Dict[str, Any]:
    from openinvest.utils.exchange_fee import get_history_data

    out = []
    for key, name, code in ASSETS:
        df = get_history_data(code, "2y")
        d = df.index.strftime("%Y-%m-%d")
        df = df[(d >= CHART_FROM) & (d <= GAME_TO)]
        days = list(df.index.strftime("%Y-%m-%d"))
        closes = [round(float(x), 4) for x in df["Close"]]
        decisions = {}
        for d in days:
            f = root / "memory" / ".backtest" / d / f"{_safe(code)}.md"
            if f.exists():
                v, why = parse_transcript(f.read_text(encoding="utf-8", errors="replace"))
                if v:
                    decisions[d] = (v, why)
        turns = pick_turns(days, decisions, GAME_FROM)
        missing = sum(t["v"] is None for t in turns)
        print(f"{code}: {len(days)} 天行情，{len(turns)} 周，其中 {missing} 周没有 AI 决定", file=sys.stderr)
        out.append({"key": key, "name": name, "code": code, "d": days, "c": closes, "turns": turns})
    return {"generated": date.today().isoformat(), "assets": out}


if __name__ == "__main__":
    from openinvest.paths import INVEST_ROOT

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(INVEST_ROOT), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)", file=sys.stderr)
