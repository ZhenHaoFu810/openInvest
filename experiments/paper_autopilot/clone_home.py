"""把一个 INVEST_HOME 的「起点」克隆成模拟账户用的新 INVEST_HOME（同起点原则）。

只复制三份用户自己的文件：memory/user.md、memory/strategy.md、memory/portfolio.md
（同样的持仓、同样的现金）。**不复制**历史：.committee/ .dreams/ .state/ .backtest*/ trades.db、
portfolio_history.jsonl 等一概不带——新账户的账本从零开始。portfolio.md 里每条 holding 的 channel
改成 paper_autopilot，并丢掉幂等键表 / 同步标记；另写 memory/.autopilot_origin.json。
拒绝覆盖已存在的 dst。脚本不含任何数据，只是复制你自己机器上的文件。

用法（仓库根）：
    uv run python experiments/paper_autopilot/clone_home.py --src <生产 INVEST_HOME> --dst <新 INVEST_HOME>
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from openinvest.core.memory_store import MemoryStore
from openinvest.core.portfolio_manager import PortfolioManager

CHANNEL = "paper_autopilot"
COPY_VERBATIM = ("user", "strategy")
# 属于「旧账本」的 portfolio.md 元数据：新账户从零开始，不能带着旧幂等键 / 已同步的 trade id
DROP_PORTFOLIO_KEYS = ("ledger_idempotency_keys", "synced_trade_ids")


def _total_cny(pm: PortfolioManager):
    """起点总资产（CNY，最佳努力：拉不到现价的持仓按成本价）；估不出来返回 None，不挡克隆。"""
    try:
        from openinvest.utils.fx import total_portfolio_value
        from openinvest.utils.quotes import get_quote
        prices = {}
        for h in pm.holdings:
            snap = get_quote(h)
            prices[h["symbol"]] = snap.price if snap else h.get("avg_cost")
        return round(total_portfolio_value(pm, prices)[0], 2)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 估不出 src_total_cny: {e}", file=sys.stderr)
        return None


def clone(src: Path, dst: Path) -> dict:
    src_mem, dst_mem = src / "memory", dst / "memory"
    for name in (*COPY_VERBATIM, "portfolio"):
        if not (src_mem / f"{name}.md").exists():
            raise SystemExit(f"src 缺 {src_mem / (name + '.md')}")
    if dst_mem.exists() and any(dst_mem.iterdir()):
        raise SystemExit(f"拒绝覆盖：{dst_mem} 已存在且非空")
    dst_mem.mkdir(parents=True, exist_ok=True)

    for name in COPY_VERBATIM:
        shutil.copy2(src_mem / f"{name}.md", dst_mem / f"{name}.md")

    doc = MemoryStore(src_mem).read("portfolio")
    meta = {k: v for k, v in doc.metadata.items()
            if k not in ("name", "type", "updated", *DROP_PORTFOLIO_KEYS)}
    meta["holdings"] = [{**h, "channel": CHANNEL} for h in (meta.get("holdings") or [])]
    MemoryStore(dst_mem).write("portfolio", doc.type, meta, doc.body)
    pm = PortfolioManager(MemoryStore(dst_mem))
    with pm.with_portfolio_tx():   # 空事务：校验 schema + 按新 channel 重渲染 body
        pass

    origin = {"cloned_at": datetime.now().isoformat(timespec="seconds"),
              "src_total_cny": _total_cny(pm)}
    (dst_mem / ".autopilot_origin.json").write_text(
        json.dumps(origin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return origin


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, type=Path, help="生产 INVEST_HOME（含 memory/）")
    ap.add_argument("--dst", required=True, type=Path, help="新 INVEST_HOME（不存在或空）")
    a = ap.parse_args()
    print(json.dumps({"status": "ok", "dst": str(a.dst), **clone(a.src.resolve(), a.dst.resolve())},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
