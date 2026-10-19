"""NaN / inf 金额不能写进账本。

NaN 能穿过 PortfolioManager 里 `amount <= 0`、`current < amount` 这类守卫（比较恒为 False）。
此前 `deposit -a nan` 会把 `CNY: .nan` 写进 portfolio.md 并返回 ok，之后每笔存款都被 NaN 吞掉。
现在 with_portfolio_tx 提交前的 schema 校验拒收非有限数：整笔不落盘，流水也不追加。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from openinvest.core.memory_store import MemoryStore
from openinvest.core.portfolio_manager import PortfolioManager
from openinvest.core.schemas import validate_portfolio


def _pm(tmp_path):
    s = MemoryStore(tmp_path / "memory")
    s.write("user", "user", {"display_name": "T", "risk_tolerance": "Balanced"}, "# user")
    s.write("strategy", "strategy", {"target_assets": []}, "# strategy")
    s.write("portfolio", "state", {"cash": {"CNY": 1000.0}, "holdings": [], "schema_version": 2}, "# p")
    return PortfolioManager(s), s


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_schema_rejects_non_finite_cash_and_units(bad):
    with pytest.raises(ValidationError):
        validate_portfolio({"cash": {"CNY": bad}, "holdings": [], "schema_version": 2})
    holding = {"symbol": "AAPL", "kind": "equity", "units": 1.0, "avg_cost": 1.0, "cost_currency": "USD"}
    for field in ("units", "avg_cost"):
        with pytest.raises(ValidationError):
            validate_portfolio({"cash": {}, "schema_version": 2, "holdings": [{**holding, field: bad}]})


@pytest.mark.parametrize("op", ["deposit_cash", "withdraw_cash"])
def test_nan_amount_leaves_ledger_untouched(tmp_path, op):
    pm, store = _pm(tmp_path)
    before = (store.root / "portfolio.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        getattr(pm, op)("CNY", float("nan"))
    assert (store.root / "portfolio.md").read_text(encoding="utf-8") == before
    assert store.read_history() == []
    assert pm.cash_amount("CNY") == 1000.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_entry_points_reject_non_finite_with_clear_message(tmp_path, bad):
    pm, _ = _pm(tmp_path)
    for call in (
        lambda: pm.deposit_cash("CNY", bad),
        lambda: pm.withdraw_cash("CNY", bad),
        lambda: pm.buy("AAPL", bad, 1.0, currency="USD"),
        lambda: pm.buy("AAPL", 1.0, bad, currency="USD"),
        lambda: pm.sell("AAPL", bad, 1.0),
        lambda: pm.sell("AAPL", 1.0, bad),
    ):
        with pytest.raises(ValueError, match="有限数"):
            call()


def test_corrupted_ledger_write_names_field_and_manual_fix(tmp_path):
    """portfolio.md 里已有 .nan：后续任何写入要报出字段路径 + 手动修 portfolio.md 的提示"""
    pm, store = _pm(tmp_path)
    store.write("portfolio", "state",
                {"cash": {"CNY": float("nan"), "AUD": 5.0}, "holdings": [], "schema_version": 2}, "# p")
    with pytest.raises(ValueError, match=r"cash\.CNY.*portfolio\.md"):
        pm.deposit_cash("AUD", 10)


def test_web_cash_body_rejects_nan_and_inf():
    from openinvest.connectors.web_api.models import CashWriteRequest
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            CashWriteRequest(amount=bad)
