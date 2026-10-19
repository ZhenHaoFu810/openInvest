---
type: wiki-chapter
title: 全自动模拟账户（paper autopilot）
tags: [paper-autopilot, execution, experiment, ledger, idempotency, opt-in]
intent: opt-in 执行层：在独立 INVEST_HOME 里把当日委员会裁决按确定性规则在本地账本成交，用来对照"人执行"的收益
schema_source:
  - src/openinvest/jobs/paper_autopilot.py:run
  - src/openinvest/core/config/tunable.py:AutopilotConfig
  - src/openinvest/core/decision_ledger.py:record_execution
documents:
  endpoints: []
  config_keys:
    - autopilot.enabled
    - autopilot.commission_bps
    - autopilot.min_order_cny
  symbols:
    - autopilot_daily
    - record_fee
    - record_execution
---

# 全自动模拟账户（paper autopilot）

**目的**：验证「人是执行里最不稳定的因素」——同一套委员会、同一个模型、同一起点，一个账户由人执行，一个由程序 100% 照做，比较收益。
**开启后，这个 INVEST_HOME 里的每条 ACCUMULATE / BUY / TRIM / SELL 裁决都会在当天收盘价上自动记账成交；HOLD 不动；裁决规则本身一字不改。**
它不下真单、不碰真实账户，`autopilot.enabled` 默认关（job 直接 no-op，fork 用户零影响）。**只应在独立的模拟 INVEST_HOME 开**，不要在记真实持仓的 home 里开。

操作手册（克隆脚本、cron、对比方法）：[`experiments/paper_autopilot/README.md`](../../experiments/paper_autopilot/README.md)。

## 流程

`openinvest autopilot_daily` = `daily_report`（不发邮件）→ `paper_autopilot` → `verdict_review`，三段各自隔离失败。
`paper_autopilot` 只处理「今天的、还没有 execution 记录的」方向性裁决（`list_decisions` 的 `execution is None`），先卖后买。
成交后 `record_execution(decision_id, executed=True, reason="paper_autopilot")`，`decisions` 的决议↔成交匹配成立。

## 成交规则

| 裁决 | 行为 |
|---|---|
| HOLD / UNCLEAR / 无 alloc | 不动，不记 execution |
| ACCUMULATE / BUY | `|alloc_cny|` 等值，当日 close，向下取整到整手 |
| TRIM | 卖 `|alloc_cny|` 等值（整手、≤ 持有量） |
| SELL | 全部卖出 |
| 场外基金（`FUND:` 开头，T+1 两段式） | 不成交，记 `executed=false`，reason `unsupported_otc_fund` |

- 必须有当日 bar：没拉到 → `stale_quote`，最新 bar 非今天 → `market_closed`（北京日期口径，美股 / 欧股不支持）；都不动账本、当日可重试。
- 手数：`.SS/.SZ` 100、`.HK` 100、`.AX` 1、金属 / 加密小数 4 位；黄金 GC=F 按 CNY/克。
- 现金不足：先按当日汇率从 CNY 换汇（`withdraw` + `deposit`），再不够缩量到整手，缩到 0 → `no_cash`；现金不为负。
- 金额 < `autopilot.min_order_cny` 或取整为 0 → `too_small`；TRIM / SELL 无持仓 → `no_position`。终局性跳过记 `executed=false`。
- 手续费 = 成交额 × `commission_bps/1e4`，作为 ADR-027 的 `fee` 活动（`record_fee`）另记一行。

## 幂等（ADR-016）

每个 `(date, symbol, side)` 一把 `state_claim("paper_autopilot", …)`；`buy / sell / fee / fx` 各带 `idempotency_key`
（`paper-{date}-{symbol}-{buy|sell}`、`paper-fee-…`、`paper-fx-{date}-{symbol}-{ccy}-out|in`）。账本写入一旦提交就不再 unclaim；
只有什么都没写的前置失败（陈旧行情 / 休市 / 取价失败）才 unclaim。

## 配置

见 [22-configuration.md](22-configuration.md)：`autopilot.enabled` / `autopilot.commission_bps` / `autopilot.min_order_cny`。
开：`INVEST_HOME=<模拟 home> openinvest config --set autopilot.enabled true`。调度：`jobs/paper_autopilot.yml`（平日 16:35，仅带 scheduler 的 home）。
