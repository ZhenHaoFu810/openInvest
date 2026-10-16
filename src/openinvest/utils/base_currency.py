"""基准币种 helper（2026-10 基准币种第 1 步）：读配置、把按人民币标定的金额阈值换成基准币种、格式化金额。

阈值继续按人民币标定（保住现有校准），运行时换算——不给每种货币各配一套。
base=CNY 时全部原样返回：人民币用户的委员会提示词和持仓摘要逐字不变。
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Optional

log = logging.getLogger(__name__)

# 委员会提示词里按人民币标定的金额（原先写死在 risk_officer.md / cio.md 里）
DRY_POWDER_LOW_CNY = 1000    # 子弹低于它 = 流动性风险
DRY_POWDER_THIN_CNY = 5000   # 子弹低于它 = 不再加大仓位
EXAMPLE_LOSS_CNY = 2000      # 模板里"再跌 20% 损失金额"的示例


def base_currency() -> str:
    """配置里的基准币种（ISO 三字母，大写）；没配 = CNY。"""
    from openinvest.core.config import load_config
    return str(load_config().portfolio.base_currency or "").strip().upper() or "CNY"


def from_cny(amount_cny: float, base: Optional[str] = None) -> int:
    """人民币标定的金额 → 基准币种整数，取两位有效数字（1000 CNY ≈ 210 AUD）。

    拉不到汇率时原数返回并告警：阈值偏松，但委员会照常能跑。
    """
    base = base or base_currency()
    if base == "CNY" or not amount_cny:
        return int(amount_cny)
    from openinvest.utils.fx import to_base
    v = to_base("CNY", float(amount_cny), base)
    if v is None or not math.isfinite(v) or v <= 0:
        log.warning("base_currency: CNY→%s 汇率不可用，金额阈值 %s 按原数使用", base, amount_cny)
        return int(amount_cny)
    # ponytail: 两位有效数字够阈值用；不足 1 个单位的币种（极弱币以外不会出现）按 1 计
    return max(1, int(round(v, 1 - int(math.floor(math.log10(v))))))


def money(amount: float, base: Optional[str] = None) -> str:
    """基准币种金额：CNY 写 ¥1,234（与历史文本一致），其它写 1,234 AUD（¥ 与日元混淆，不用符号）。"""
    base = base or base_currency()
    return f"¥{amount:,.0f}" if base == "CNY" else f"{amount:,.0f} {base}"


def alloc_ceiling(base: Optional[str] = None) -> int:
    """CIO 单笔建议金额上限（verdict.alloc_cny_ceiling，按人民币标定）换成基准币种。"""
    from openinvest.core.config import load_config
    return from_cny(load_config().verdict.alloc_cny_ceiling, base)


def prompt_vars() -> Dict[str, object]:
    """委员会提示词模板的币种占位符（capabilities.loader.load_skill 统一注入）。"""
    base = base_currency()
    return {
        "BASE": base,
        "base": base.lower(),
        "BASE_NAME": "人民币" if base == "CNY" else base,
        "CUR": "¥" if base == "CNY" else f"{base} ",
        "DRY_POWDER_LOW": from_cny(DRY_POWDER_LOW_CNY, base),
        "DRY_POWDER_THIN": from_cny(DRY_POWDER_THIN_CNY, base),
        "ALLOC_CEILING": alloc_ceiling(base),
        "EXAMPLE_LOSS": money(from_cny(EXAMPLE_LOSS_CNY, base), base),
    }


__all__ = ["alloc_ceiling", "base_currency", "from_cny", "money", "prompt_vars"]
