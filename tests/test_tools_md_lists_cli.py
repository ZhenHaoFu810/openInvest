"""tools.md 自称子命令表是"闭集"——那它必须列全 CLI 的每个子命令（2026-10）

曾漏掉 track_asset / untrack_asset / set_allocations / news_sources / event_check / daily_report，
只读这份文档的 agent 会以为这些命令不存在。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from openinvest.cli import build_parser

TOOLS_MD = Path(__file__).resolve().parents[1] / "plugin/skills/invest/references/tools.md"


def test_tools_md_table_lists_every_cli_subcommand():
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    documented = set(re.findall(r"^\| `([a-z_]+)", TOOLS_MD.read_text(encoding="utf-8"), re.M))
    missing = sorted(set(sub.choices) - documented)
    assert not missing, f"tools.md 的子命令表漏了：{missing}"
