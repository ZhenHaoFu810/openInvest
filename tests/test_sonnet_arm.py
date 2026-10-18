"""纸面舰队 Sonnet 模型臂（backtest_committee --sonnet-arm）——写侧 + 复盘侧契约测试。

守：
- config fleet.sonnet_arm 默认值 / YAML 可覆盖
- LLM 覆盖只在臂作用域内（get_llm_config / _safe / 新建 agent 都是 Sonnet），退出（含异常）即还原
- 缺 FLEET_SONNET_API_KEY：该臂不花钱地跳过、其余臂照跑、退出码非 0
- main() 调度：Sonnet 臂最后一个跑、不借对照臂的 macro_view、rounds 不变、带 arm 标签；只能配 --prospective
- 复盘：模型臂的行不因 macro_shared=False 被剔（其余臂照旧剔）；报告单列「模型对照」、稳定度标 n/a；
  臂一览 / 四臂并排不被模型臂污染
不联网、不调 LLM。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import pytest

from openinvest.jobs import review_calc as rc
from openinvest.jobs import verdict_review as vr
from scripts import backtest_committee as bc


# ---------- config ----------

def test_fleet_sonnet_arm_config_defaults_and_yaml_override(tmp_path):
    from openinvest.core.config import load_config, reset_config
    reset_config()
    c = load_config().fleet.sonnet_arm
    assert (c.model, c.base_url, c.api_key_env) == (
        "claude-sonnet-5-5", "https://api.anthropic.com/v1", "FLEET_SONNET_API_KEY")
    y = tmp_path / "c.yaml"
    y.write_text("fleet:\n  sonnet_arm:\n    model: claude-sonnet-x\n", encoding="utf-8")
    try:
        c2 = load_config(y).fleet.sonnet_arm
        assert c2.model == "claude-sonnet-x" and c2.api_key_env == "FLEET_SONNET_API_KEY"   # 只写想改的键
    finally:
        reset_config()


# ---------- 作用域内覆盖 ----------

@pytest.fixture
def deepseek_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "ds-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("FLEET_SONNET_API_KEY", "sonnet-key")
    from openinvest.core.config import reset_config
    reset_config()
    yield
    reset_config()


DS = ("ds-key", "https://api.deepseek.com", "deepseek-v4-flash", "openai")
SONNET = ("sonnet-key", "https://api.anthropic.com/v1", "claude-sonnet-5-5", "openai")


def test_llm_override_only_inside_arm_scope_and_restored_even_on_error(deepseek_env):
    from openinvest.utils import llm
    assert llm.get_llm_config() == DS and llm.get_llm_config_safe() == DS
    with bc._sonnet_arm() as cfg:
        assert cfg.model == "claude-sonnet-5-5"
        assert llm.get_llm_config() == SONNET and llm.get_llm_config_safe() == SONNET
        assert llm.get_llm_config_safe(default_model="x") == SONNET        # 带默认值参数的调用点也走覆盖
        assert llm.is_claude()                                              # 依赖模型名的开关跟着变
    assert llm.get_llm_config() == DS and llm.get_llm_config_safe() == DS   # 退出即还原
    with pytest.raises(RuntimeError, match="boom"):
        with bc._sonnet_arm():
            assert llm.get_llm_config() == SONNET
            raise RuntimeError("boom")
    assert llm.get_llm_config() == DS and llm.get_llm_config_safe() == DS   # 异常退出也还原
    assert not llm.is_claude()


def test_agent_created_inside_scope_talks_to_sonnet_and_not_outside(deepseek_env):
    from openinvest.core.committee.agent_io import _create_agent
    out = _create_agent("sys", role="quant")
    assert out.model == "deepseek-v4-flash" and str(out.client.base_url).startswith("https://api.deepseek.com")
    with bc._sonnet_arm():
        inside = _create_agent("sys", role="quant")
    assert inside.model == "claude-sonnet-5-5"
    assert str(inside.client.base_url).startswith("https://api.anthropic.com/v1")
    assert inside.client.api_key == "sonnet-key"
    assert _create_agent("sys", role="quant").model == "deepseek-v4-flash"


def test_missing_key_means_arm_cannot_start_and_nothing_is_patched(deepseek_env, monkeypatch):
    from openinvest.utils import llm
    monkeypatch.delenv("FLEET_SONNET_API_KEY")
    with pytest.raises(bc.SonnetArmUnavailable, match="FLEET_SONNET_API_KEY"):
        with bc._sonnet_arm():
            pytest.fail("不该进入作用域")
    monkeypatch.setenv("FLEET_SONNET_API_KEY", "   ")                       # 全空白也算没设
    with pytest.raises(bc.SonnetArmUnavailable):
        with bc._sonnet_arm():
            pytest.fail("不该进入作用域")
    assert llm.get_llm_config() == DS


# ---------- main() 调度 ----------

def _prospective_main(monkeypatch, argv, fake_run_one_day):
    import openinvest.db.market_store as ms_mod

    class _Store:
        def get_history_df(self, sym, days=5):
            return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([datetime.now().date()]))

    monkeypatch.setattr(ms_mod, "MarketStore", _Store)
    monkeypatch.setattr(bc, "run_one_day", fake_run_one_day)
    monkeypatch.setattr("sys.argv", ["backtest_committee", "--prospective", "--assets", "AAA,BBB", *argv])
    bc.main()


def test_main_runs_sonnet_arm_last_with_own_macro_inside_override(deepseek_env, monkeypatch):
    from openinvest.utils import llm
    seen: List[Dict[str, Any]] = []

    def fake(d, syms, **kw):
        seen.append({"llm": llm.get_llm_config_safe()[2], **kw})
        return {"date": d, "macro_view": "MACRO-X", "verdicts": {s: {"verdict": "HOLD"} for s in syms}}

    _prospective_main(monkeypatch, ["--debate-arm", "--sonnet-arm"], fake)
    assert [k["llm"] for k in seen] == ["deepseek-v4-flash", "deepseek-v4-flash", "claude-sonnet-5-5"]
    control, debate_kw, sonnet = seen
    assert "out_subdir" not in control
    assert debate_kw["out_subdir"] == bc.DEBATE_ARM_SUBDIR
    assert sonnet["out_subdir"] == bc.SONNET_ARM_SUBDIR == ".backtest_sonnet"
    assert sonnet["arm_health"] == {"arm": "sonnet_live_cfg"}
    assert "macro_view_override" not in sonnet, "Macro 由 Sonnet 自己生成，不借对照臂的"
    assert "max_rounds_override" not in sonnet and "votes" not in sonnet, "live 配置：rounds=1、单次抽样"
    assert llm.get_llm_config_safe()[2] == "deepseek-v4-flash"               # 跑完还原


def test_main_missing_key_skips_only_sonnet_arm_and_exits_nonzero(deepseek_env, monkeypatch):
    monkeypatch.delenv("FLEET_SONNET_API_KEY")
    seen: List[Dict[str, Any]] = []

    def fake(d, syms, **kw):
        seen.append(kw)
        return {"date": d, "macro_view": "M", "verdicts": {s: {"verdict": "HOLD"} for s in syms}}

    with pytest.raises(SystemExit) as ei:
        _prospective_main(monkeypatch, ["--debate-arm", "--sonnet-arm"], fake)
    assert ei.value.code == 1
    assert [k.get("out_subdir") for k in seen] == [None, bc.DEBATE_ARM_SUBDIR]   # 对照 / debate 照跑，Sonnet 没花钱


def test_main_sonnet_arm_failure_exits_nonzero(deepseek_env, monkeypatch):
    def fake(d, syms, **kw):
        if kw.get("out_subdir") == bc.SONNET_ARM_SUBDIR:
            return {"date": d, "verdicts": {"AAA": {"error": "429"}, "BBB": {"verdict": "HOLD"}}}
        return {"date": d, "macro_view": "M", "verdicts": {s: {"verdict": "HOLD"} for s in syms}}

    with pytest.raises(SystemExit) as ei:
        _prospective_main(monkeypatch, ["--sonnet-arm"], fake)
    assert ei.value.code == 1


def test_sonnet_arm_requires_prospective_and_rounds_env(deepseek_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["backtest_committee", "--sonnet-arm", "--days", "1"])
    with pytest.raises(SystemExit, match="--prospective"):
        bc.main()
    monkeypatch.setenv("INVEST_MAX_DEBATE_ROUNDS", "2")
    seen: List[Any] = []
    with pytest.raises(SystemExit, match="INVEST_MAX_DEBATE_ROUNDS"):
        _prospective_main(monkeypatch, ["--sonnet-arm"], lambda d, s, **kw: seen.append(1))
    assert seen == [], "拒绝发生在花钱之前"


def test_run_one_day_sonnet_arm_records_real_model_and_unshared_macro(deepseek_env, monkeypatch, tmp_path):
    """端到端（LLM 桩）：臂内 run_committee 看到的是 Sonnet 配置，落盘 Input Health 带 arm 标签 + 真实模型名，
    macro_shared 为 False（Macro 是 Sonnet 自己生成的，不是对照臂那份）。"""
    import openinvest.core.committee as committee
    import openinvest.core.committee.persist as persist
    import openinvest.core.memory_store as mem_mod
    import openinvest.db.market_store as ms_mod
    import openinvest.utils.exchange_fee as ef
    from openinvest.core.committee.debate import CommitteeReport
    from openinvest.core.decision_ledger import parse_committee_text
    from openinvest.utils import llm   # 必须走模块属性：`from ... import get_llm_config_safe` 会在 patch 前绑死原函数

    day = "2020-02-14"
    monkeypatch.setattr(mem_mod, "MEMORY_ROOT", tmp_path / "memory")
    monkeypatch.setattr(ms_mod, "DB_PATH", str(tmp_path / "market.db"))
    store = ms_mod.MarketStore()
    for i, d in enumerate(pd.bdate_range("2019-06-03", day)):
        store.save_generic_price("AAPL", d.strftime("%Y-%m-%d"), 100.0 + 0.5 * i,
                                 high=101.0 + 0.5 * i, low=99.0 + 0.5 * i, volume=1e6)
    monkeypatch.setattr(ef, "_STORE", store)
    monkeypatch.setattr(ef, "get_macro_data", lambda: "macro-data")
    monkeypatch.setattr(persist, "_capture_macro_context", lambda as_of_date=None: {"captured_at": as_of_date})
    ctrl = tmp_path / "memory" / ".backtest" / day
    ctrl.mkdir(parents=True)
    (ctrl / "AAPL.md").write_text("CONTROL MACRO-DEEPSEEK", encoding="utf-8")

    monkeypatch.setattr(committee, "run_macro_view",
                        lambda data, **kw: f"MACRO-BY-{llm.get_llm_config_safe()[2]}\nSIGNAL: risk_off\nSTRENGTH: 6")

    def fake_run_committee(**kw):
        verdict = {"verdict": "HOLD", "confidence": 0.62, "dominant_view": "quant", "alloc_cny": 0}
        report = CommitteeReport(asset=kw["asset"], macro_view=kw["macro_view"], quant_view="Q", risk_view="R",
                                 cio_memo="CIO")
        return {"asset": kw["asset"]["symbol"], "verdict": verdict, "report": report,
                "debate": {"max_rounds": kw["max_debate_rounds"], "final_round": 1, "converged": False,
                           "quant_history": [], "risk_history": [], "model": llm.get_llm_config_safe()[2],
                           "cio_json_mode": True}}

    monkeypatch.setattr(committee, "run_committee", fake_run_committee)
    with bc._sonnet_arm():
        bc.run_one_day(day, ["AAPL"], out_subdir=bc.SONNET_ARM_SUBDIR, arm_health={"arm": bc.SONNET_ARM_TAG})
    text = (tmp_path / "memory" / bc.SONNET_ARM_SUBDIR / day / "AAPL.md").read_text(encoding="utf-8")
    h = parse_committee_text(text)["input_health"]
    assert h["arm"] == "sonnet_live_cfg" and h["model"] == "claude-sonnet-5-5"
    assert h["macro_shared"] is False and h["macro_signal"] == "risk_off"
    assert "MACRO-BY-claude-sonnet-5-5" in text                              # Macro 是 Sonnet 生成的
    assert rc.model_era_of(h, day) == "direct:claude-sonnet-5-5"


# ---------- 复盘：模型臂不按 macro_shared 剔行 ----------

def _rv(day, asset, verdict, *, arm=None, shared=None, model="claude-sonnet-5-5", ret=0.01, hit=True, mkt="flat"):
    health = {"schema": 1, "model": model}
    if arm:
        health["arm"] = arm
    if shared is not None:
        health["macro_shared"] = shared
    rv = rc.VerdictReview(date=day, asset=asset, verdict=verdict, confidence=0.6,
                          expected_direction=rc.EXPECTED_DIRECTION.get(verdict, "none"), macro_at_decision={},
                          input_health=health)
    rv.actual_returns["30d"], rv.directions["30d"], rv.hits["30d"] = ret, mkt, hit
    return rv


def test_model_arm_rows_are_not_dropped_for_unshared_macro_but_other_arms_still_are():
    days = ("2026-08-03", "2026-08-04", "2026-08-05")
    ctl = [_rv(d, "A", "HOLD", model="deepseek-v4-flash") for d in days]
    sonnet = [_rv(d, "A", "ACCUMULATE", arm="sonnet_live_cfg", shared=False) for d in days]
    debate = [_rv(d, "A", "HOLD", arm="debate_r4", shared=False, model="deepseek-v4-flash") for d in days]
    assert all(rc._arm_row_ok(r) for r in sonnet)
    assert not any(rc._arm_row_ok(r) for r in debate)                          # 其余臂：照旧剔
    assert rc.macro_unshared_count(sonnet) == 0 and rc.macro_unshared_count(debate) == 3
    cmp_ = rc.arm_vs_control(sonnet, ctl, min_n=2)
    assert cmp_["matched"] == 3 and cmp_["arm_total"] == 3
    assert rc.arm_vs_control(debate, ctl, min_n=2)["matched"] == 0


def test_arms_report_has_model_comparison_section_with_unshared_macro_note_and_na_stability():
    days = ("2026-08-03", "2026-08-04", "2026-08-05")
    ctl = [_rv(d, "A", "HOLD", model="deepseek-v4-flash") for d in days]
    sonnet = [_rv(d, "A", "ACCUMULATE", arm="sonnet_live_cfg", shared=False) for d in days]
    txt = "\n".join(rc.arms_report_lines({"sonnet": sonnet}, ctl, min_n=2))
    assert "## 模型对照（sonnet 臂 vs 对照臂" in txt
    assert "Macro 视图不共享" in txt and "不因此剔行" in txt
    assert "臂内稳定度（逐票翻转 / 一致率 / 无多数）：**n/a**" in txt
    assert "## 臂内稳定度" not in txt                                          # 没有逐票记录，不出稳定度节
    assert "## 配对对照（sonnet vs 对照臂 · 同日同标的 3 个" in txt
    assert "两臂的 market_data / regime / 中性持仓 / macro_view 逐字相同" not in txt   # 模型臂 macro 不同，不能沿用这句
    assert "direct:claude-sonnet-5-5 × 3" in txt and "direct:deepseek-v4-flash × 3" in txt
    assert "不止一个模型" not in txt                                           # 模型臂换模型是设计变量，不算混用
    assert "## 并排" not in txt and "## H3" not in txt                         # 只有模型臂：四臂并排整段不出
    row = next(ln for ln in txt.splitlines() if ln.startswith("| sonnet | sonnet"))
    assert "n/a（模型臂的 Macro 本就由它自己生成" in row


def test_four_arm_sections_are_unchanged_by_a_model_arm():
    days = ("2026-08-03", "2026-08-04")
    ctl = [_rv(d, "A", "HOLD", model="deepseek-v4-flash") for d in days]
    debate = [_rv(d, "A", "HOLD", arm="debate_r4", shared=True, model="deepseek-v4-flash") for d in days]
    sonnet = [_rv(d, "A", "TRIM", arm="sonnet_live_cfg", shared=False) for d in days]
    base = "\n".join(rc.arms_report_lines({"debate": debate}, ctl, min_n=2))
    both = "\n".join(rc.arms_report_lines({"debate": debate, "sonnet": sonnet}, ctl, min_n=2))
    # 四臂并排 → … → 判据脚注：有没有模型臂都逐字相同（模型臂不进 side_by_side 的键交集 / H1–H3）
    four_both = both.split("## 并排", 1)[1].split("\n## 模型对照", 1)[0]
    assert four_both.rstrip() == base.split("## 并排", 1)[1].rstrip()
    assert "## 模型对照" in both and "## 模型对照" not in base
    # 「不止一个模型」只看对照臂 + 四臂：这里都是 deepseek，不该因为 sonnet 臂报警
    assert "不止一个模型" not in both


def test_run_arms_reads_sonnet_dir_into_its_own_jsonl(monkeypatch, tmp_path):
    assert vr.ARM_DIRS["sonnet"] == vr.SONNET_ARM_SUBDIR == ".backtest_sonnet"
    seen: List[str] = []
    monkeypatch.setattr(vr, "review_arm", lambda sub, *, name: seen.append(name) or [])
    monkeypatch.setattr(vr, "MemoryStore", lambda: (_ for _ in ()).throw(AssertionError("无行时不该写任何东西")))
    assert vr.run_arms()["status"] == "skipped"
    assert seen == ["sealed", "debate", "macrosoft", "sonnet"]
