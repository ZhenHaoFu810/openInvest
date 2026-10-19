"""history 的 recent_debates 读 memory/.committee/<date>/*.md（当前所有 transcript 的落盘位置）。

此前读的是早已无人写入的 memory/.debate：老实例只返回几份旧文件，新装恒为空。
"""
from __future__ import annotations


def test_recent_debates_read_committee_date_dirs(tmp_path, monkeypatch):
    mem = tmp_path / "memory"
    legacy = mem / ".debate" / "2026-04-28"
    legacy.mkdir(parents=True)
    (legacy / "GC_F.md").write_text("# legacy", encoding="utf-8")
    for d in ("2026-10-16", "2026-10-17"):
        (mem / ".committee" / d).mkdir(parents=True)
        (mem / ".committee" / d / "GC_F.md").write_text(f"# Committee {d}\n**Verdict**: HOLD", encoding="utf-8")
    runs = mem / ".committee" / "2026-10-17" / "runs"          # 同日重跑归档，不算新的一份
    runs.mkdir()
    (runs / "GC_F_101500.md").write_text("# earlier run", encoding="utf-8")
    task = mem / ".committee" / "3f9c2a7b1d04"                  # task 状态目录（hash 名）
    task.mkdir()
    (task / "status.md").write_text("task", encoding="utf-8")

    from openinvest.core import memory_store as ms
    monkeypatch.setattr(ms, "MEMORY_ROOT", mem)
    from openinvest.services.skill_views import build_history_view

    out = build_history_view(5)["recent_debates"]
    assert [(d["date"], d["asset"]) for d in out] == [("2026-10-17", "GC_F"), ("2026-10-16", "GC_F")]
    assert out[0]["summary"].startswith("# Committee 2026-10-17")
