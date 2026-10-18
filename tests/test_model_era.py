"""模型分桶（model_era）：换模型（#483 deepseek-v4-flash → claude-sonnet-5-5）后新旧账分开算。

守：model_era 口径（Direct / Coordinator / 老存档按日期）、holdout 内按模型分子桶 + n<30 只给 n、
查表只用同模型样本（不够退默认表并注明）、公开 JSON 的 by_model 抑制（含互补抑制）、四臂报告标模型。
不联网、不调 LLM。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openinvest.jobs import review_calc as rc
from scripts.export_accuracy import MIN_SAMPLE_FOR_PUBLIC, build_summary

PRE = rc.PRE_HEALTH_ERA                      # direct:deepseek-v4-flash(pre-health)
SONNET_H = {"schema": 1, "model": "claude-sonnet-5-5"}
SONNET = "direct:claude-sonnet-5-5"


# ---------- model_era 口径 ----------

@pytest.mark.parametrize("health,date,want", [
    ({"schema": 1, "model": "claude-sonnet-5-5"}, "2026-10-19", "direct:claude-sonnet-5-5"),
    ({"schema": 1, "model": "deepseek-v4-flash"}, "2026-10-14", "direct:deepseek-v4-flash"),
    ({"schema": 1}, "2026-10-19", "direct:unknown"),                       # 有块没 model：不猜
    ({"entry": "coordinator", "provider": "hermes", "model": "claude-haiku-5-5"}, "2026-10-20",
     "hermes:claude-haiku-5-5"),
    ({"entry": "coordinator", "provider": "claude", "model": "unknown"}, "2026-10-20", "claude:unknown"),
    ({"entry": "coordinator", "provider": "Hermes"}, "2026-10-20", "hermes:unknown"),   # 老 Coordinator 行没 model
    ({}, "2026-07-01", PRE),                                               # 老存档按日期归
    ({}, "2026-10-18", PRE),                                               # 边界：≤ cutoff
    ({}, "2026-10-19", "unknown"),                                         # cutoff 之后没块 → 不猜
    (None, "2026-10-19", "unknown"),
])
def test_model_era_of(health, date, want):
    assert rc.model_era_of(health, date) == want


def test_review_derives_model_era_and_keeps_explicit_one():
    r = rc.VerdictReview(date="2026-10-20", asset="X", verdict="HOLD", confidence=0.6,
                         expected_direction="flat", macro_at_decision={}, input_health=dict(SONNET_H))
    assert r.model_era == SONNET
    assert rc.VerdictReview(date="2026-07-01", asset="X", verdict="HOLD", confidence=0.6,
                            expected_direction="flat", macro_at_decision={}).model_era == PRE
    e = rc.VerdictReview(date="2026-07-01", asset="X", verdict="HOLD", confidence=0.6,
                         expected_direction="flat", macro_at_decision={}, model_era="custom:m")
    assert e.model_era == "custom:m"
    assert json.loads(json.dumps(__import__("dataclasses").asdict(r)))["model_era"] == SONNET   # 落 jsonl


def test_model_key_ignores_prefix_suffix_and_colons_in_config_name():
    assert rc.era_model(PRE) == "deepseek-v4-flash" == rc.era_model("direct:deepseek-v4-flash")
    assert rc.era_model("hermes:claude-haiku-5-5") == "claude-haiku-5-5"
    assert rc.era_model("unknown") == "unknown"
    assert rc.model_key("Claude-Sonnet-5-5 ") == "claude-sonnet-5-5"
    assert rc.model_key("vendor/model:free") == "vendor/model:free"       # config 原名自带冒号不能被当 era 拆


# ---------- holdout 内按模型分子桶 ----------

def _rv(*, health=None, day="2026-09-01", verdict="HOLD", hit=True, mkt="flat", conf=0.6,
        matured=True, source="live"):
    r = rc.VerdictReview(date=day, asset="X", verdict=verdict, confidence=conf,
                         expected_direction=rc.EXPECTED_DIRECTION.get(verdict, rc.UNCLEAR_DIRECTION),
                         macro_at_decision={}, input_health=health or {}, source=source)
    if matured:
        r.hits["30d"], r.directions["30d"] = hit, mkt
        r.actual_returns["30d"] = 0.0
    return r


def test_summarize_splits_holdout_by_model_and_suppresses_small_subbucket():
    old = [_rv(hit=i % 4 != 0) for i in range(40)]                       # pre-health deepseek，40 条 30d 已成熟
    new = [_rv(health=SONNET_H, day="2026-10-20", matured=False) for _ in range(35)] \
        + [_rv(health=SONNET_H, day="2026-10-20", hit=False) for _ in range(2)]   # Sonnet：总行 37、成熟 2
    s = rc.summarize_verdict_reviews(old + new)
    bm = s["holdout"]["by_model"]
    assert list(bm) == [PRE, SONNET]                                    # 旧模型在前
    d, n = bm[PRE], bm[SONNET]
    assert d["n"] == 40 and d["by_window"]["30d"]["hit_rate"] == 0.75   # 30/40
    assert d["calibration"]["n"] == 40 and d["neutrality"]["n"] == 40
    # 总行 37 ≥ 30 但 30d 成熟只有 2：闸按成熟数，只给 n
    assert n == {"n": 37, "n_matured_30d": 2, "rates_suppressed_sub30": True,
                 "live_count": 37, "backtest_count": 0}
    # 全局 holdout 数字不变（仍是全部模型合并）
    assert s["holdout"]["n"] == 77 and s["holdout"]["by_window"]["30d"]["n"] == 42


def test_report_has_by_model_section_with_only_n_for_small_subbucket(tmp_path, monkeypatch):
    from openinvest.jobs import verdict_review as vr
    monkeypatch.setattr(vr, "ROOT", tmp_path)
    rows = [_rv(hit=i % 2 == 0) for i in range(40)] + [_rv(health=SONNET_H, day="2026-10-20", hit=True)]
    md = vr.write_report(rows, vr.summarize(rows)).read_text(encoding="utf-8")
    sec = md.split("## 按模型", 1)[1].split("## 置信度校准", 1)[0]
    assert f"| {PRE} | 40 | 40 | 50.0% |" in sec
    assert f"| {SONNET} | 1 | 1 | n<30 只给 n | — |" in sec
    assert "按模型 · " + PRE in sec and "按模型 · " + SONNET not in sec      # 小子桶没有详细分节
    assert "· 全部模型合并" in md                                           # 全局校准 / 中性度标明是合并口径


def test_single_era_report_does_not_duplicate_holdout():
    lines = "\n".join(rc._model_lines(rc.summarize_by_model([_rv() for _ in range(40)])))
    assert "只有一个 model_era" in lines and "按模型 · " not in lines


# ---------- 置信度查表：只用同模型样本 ----------

def _lk_rows(n, health=None, day="2026-06-01", **kw):
    return [_rv(health=health, day=day, **kw) for _ in range(n)]


def test_lookup_only_counts_same_model_rows():
    live = _lk_rows(40) + _lk_rows(5, SONNET_H, "2026-10-20")
    fleet = _lk_rows(10, {"schema": 1, "model": "deepseek-v4-flash"}, "2026-10-20", source="backtest")
    sonnet = rc.build_confidence_lookup(live, fleet, model="claude-sonnet-5-5")
    assert sonnet["model"] == "claude-sonnet-5-5"
    assert sonnet["by_verdict"]["HOLD"] == {"n": 5, "rate": None, "n_live": 5, "n_fleet": 0}   # 不够 30 → 无数
    ds = rc.build_confidence_lookup(live, fleet, model="deepseek-v4-flash")
    # pre-health + 有块的 DeepSeek 舰队行同模型；Sonnet 行不进
    assert ds["by_verdict"]["HOLD"] == {"n": 50, "rate": 1.0, "n_live": 40, "n_fleet": 10}
    assert "model" not in rc.build_confidence_lookup(live, fleet)                              # 不传 = 不过滤
    assert rc.build_confidence_lookup(live, fleet)["by_verdict"]["HOLD"]["n"] == 55
    # Coordinator 行：模型名对得上才算（host 没传 = unknown，永远不匹配）
    coord = _lk_rows(30, {"entry": "coordinator", "provider": "hermes", "model": "claude-sonnet-5-5"}, "2026-10-20") \
        + _lk_rows(30, {"entry": "coordinator", "provider": "claude", "model": "unknown"}, "2026-10-20")
    assert rc.build_confidence_lookup(coord, model="claude-sonnet-5-5")["by_verdict"]["HOLD"]["n"] == 30


DEFAULT = {"source": "fleet", "model": "deepseek-v4-flash", "by_verdict": {"HOLD": {
    "n": 900, "rate": 0.75, "n_live": 0, "n_fleet": 900}}, "market_flat": {"n": 900, "rate": 0.73}}


def test_insufficient_current_model_falls_back_to_default_and_says_so():
    local = rc.build_confidence_lookup(_lk_rows(40) + _lk_rows(5, SONNET_H, "2026-10-20"),
                                       model="claude-sonnet-5-5")
    merged = rc.merge_confidence_lookup(local, DEFAULT)
    assert merged["by_verdict"]["HOLD"]["from"] == "default"
    txt = rc.confidence_display({"verdict": "HOLD", "confidence": 0.62}, merged, with_raw=False)
    assert "默认表，deepseek-v4-flash 舰队样本，当前 claude-sonnet-5-5 样本不足" in txt and "n=900" in txt
    # 当前模型就是默认表的模型：照旧只写"默认表"
    same = rc.merge_confidence_lookup({**local, "model": "deepseek-v4-flash"}, DEFAULT)
    assert rc.confidence_display({"verdict": "HOLD", "confidence": 0.62}, same, with_raw=False).endswith("；默认表）")
    # 本机同模型样本够 30 → 用本机，不退默认表
    ok = rc.merge_confidence_lookup(
        rc.build_confidence_lookup(_lk_rows(35, SONNET_H, "2026-10-20"), model="claude-sonnet-5-5"), DEFAULT)
    assert ok["by_verdict"]["HOLD"]["from"] == "local" and ok["by_verdict"]["HOLD"]["n"] == 35


def test_daily_run_writes_lookup_for_the_configured_model(tmp_path, monkeypatch):
    from openinvest.core.memory_store import MemoryStore
    from openinvest.jobs import verdict_review as vr
    monkeypatch.setattr(vr, "MemoryStore", lambda: MemoryStore(tmp_path))
    monkeypatch.setattr(vr, "review_all", lambda **k: _lk_rows(40))          # 40 条 pre-health DeepSeek
    monkeypatch.setattr(vr, "write_report", lambda *a: tmp_path / "r.md")
    monkeypatch.setattr(vr, "write_jsonl", lambda *a: tmp_path / "r.jsonl")
    monkeypatch.setattr(vr, "review_fleet", lambda: [])
    dflt = tmp_path / "default.json"
    dflt.write_text(json.dumps(DEFAULT))
    monkeypatch.setattr(vr, "DEFAULT_LOOKUP_PATH", dflt)
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    vr.run()
    saved = json.loads((tmp_path / ".dreams" / "confidence_lookup.json").read_text(encoding="utf-8"))
    assert saved["model"] == "claude-sonnet-5-5" and saved["by_verdict"] == {}   # 一条同模型样本都没有
    assert vr.load_confidence_lookup()["by_verdict"]["HOLD"]["from"] == "default"
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")                    # 换回 DeepSeek → 40 条够 30
    vr.run()
    assert vr.load_confidence_lookup()["by_verdict"]["HOLD"]["from"] == "local"


# ---------- 公开 JSON：by_model ----------

def _row(*, era=None, health=None, day="2026-08-03", hit=True, matured=True, conf=0.6):
    r = {"date": day, "asset": "X", "source": "live", "expected_direction": "flat", "confidence": conf,
         "hits": {"30d": hit} if matured else {}, "directions": {"30d": "flat"} if matured else {},
         "actual_returns": {"30d": 0.0} if matured else {}, "input_health": health or {}}
    if era:
        r["model_era"] = era
    return r


def _export(tmp_path: Path, rows) -> dict:
    p = tmp_path / "v.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return build_summary(p)["windows"]["all"]


def test_public_by_model_splits_and_derives_era_for_old_rows(tmp_path):
    rows = [_row(hit=i % 2 == 0) for i in range(40)] \
        + [_row(health=SONNET_H, day="2026-10-20", hit=i % 3 == 0) for i in range(36)]
    w = _export(tmp_path, rows)                      # 老行没有 model_era 键：按 input_health + date 重算
    assert set(w["by_model"]) == {PRE, SONNET}
    assert w["by_model"][PRE]["sample_size"] == 40 and w["by_model"][PRE]["direction_hit_rate"] == 0.5
    assert w["by_model"][SONNET]["sample_size"] == 36 and w["by_model"][SONNET]["direction_hit_rate"] == 0.3333
    assert w["sample_size"] == 76                    # 窗口合计口径不变
    blob = json.dumps(w)
    assert '"asset"' not in blob and '"symbol"' not in blob and "X" not in w["by_model"]   # 红线


def test_public_by_model_small_model_suppressed_and_complement_masked(tmp_path):
    rows = [_row(hit=i % 2 == 0) for i in range(40)] \
        + [_row(health=SONNET_H, day="2026-10-20", hit=False) for _ in range(3)]
    w = _export(tmp_path, rows)
    small, big = w["by_model"][SONNET], w["by_model"][PRE]
    assert small["sample_size"] == 3 and small["direction_hit_rate"] is None
    assert small["by_direction"]["hold"]["total"] == 3 and small["by_direction"]["hold"]["hit"] is None
    # 窗口合计公开（43 条）：若大模型的数字也公开，相减就能还原那 3 条 → 互补抑制：大模型只留计数
    assert w["direction_hit_rate"] is not None
    assert big["sample_size"] == 40 and big["direction_hit_rate"] is None
    assert big["by_direction"]["hold"]["total"] == 40
    assert all(big["by_direction"]["hold"][k] is None for k in ("hit", "rate", "lift", "ci95", "base_rate"))
    assert big["calibration"]["n"] == 40 and big["calibration"]["brier"] is None
    assert big["base_rate"]["n"] == 40 and big["base_rate"]["flat"] is None


def test_public_by_model_no_mask_when_no_mature_rows_or_enough_rows(tmp_path):
    # 新模型 30d 还没成熟：sample_size 0，没有可还原的东西 → 旧模型数字照出
    rows = [_row(hit=True) for _ in range(40)] + [_row(health=SONNET_H, day="2026-10-20", matured=False)] * 4
    w = _export(tmp_path, rows)
    assert w["by_model"][SONNET]["sample_size"] == 0
    assert w["by_model"][PRE]["direction_hit_rate"] == 1.0
    # 新模型够 30：两边都出数字
    rows = [_row(hit=True) for _ in range(40)] + [_row(health=SONNET_H, day="2026-10-20", hit=False)] * MIN_SAMPLE_FOR_PUBLIC
    w = _export(tmp_path, rows)
    assert w["by_model"][SONNET]["direction_hit_rate"] == 0.0 and w["by_model"][PRE]["direction_hit_rate"] == 1.0


def test_public_by_model_prefers_stored_model_era_and_windows_each_get_it(tmp_path):
    now = datetime.now(timezone.utc)
    day = (now - timedelta(days=65)).strftime("%Y-%m-%d")
    rows = [_row(era="hermes:claude-haiku-5-5", day=day, hit=True) for _ in range(31)]
    p = tmp_path / "v.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    ws = build_summary(p)["windows"]
    assert all("by_model" in w for w in ws.values())
    assert set(ws["all"]["by_model"]) == {"hermes:claude-haiku-5-5"}


# ---------- 四臂报告标模型 ----------

def test_arm_report_labels_models_and_warns_on_mixed_models():
    ctl = [_rv(health={"schema": 1, "model": "deepseek-v4-flash"}, day="2026-10-12") for _ in range(2)]
    arm_same = {"sealed": [_rv(health={"schema": 1, "model": "deepseek-v4-flash", "arm": "sealed_n3"},
                               day="2026-10-12")]}
    txt = "\n".join(rc.arms_report_lines(arm_same, ctl))
    assert "模型（model_era × 行数）" in txt and "direct:deepseek-v4-flash × 2" in txt
    assert "不止一个模型" not in txt
    arm_mixed = {"sealed": [_rv(health={"schema": 1, "model": "claude-sonnet-5-5", "arm": "sealed_n3"},
                                day="2026-10-12")]}
    mixed = "\n".join(rc.arms_report_lines(arm_mixed, ctl))
    assert "direct:claude-sonnet-5-5 × 1" in mixed and "不止一个模型" in mixed
    assert "claude-sonnet-5-5" in mixed.split("不止一个模型", 1)[1].split("\n", 1)[0]
