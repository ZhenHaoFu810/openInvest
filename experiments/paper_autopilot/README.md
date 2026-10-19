# paper_autopilot — 全自动模拟账户（人 vs 程序的执行对照）

**目的**：作者想验证「人是执行里最不稳定的因素」。同一套委员会、同一个模型、同一起点：一个账户由人（作者）执行，
一个由程序 100% 照做，比较收益。本目录是这个对照的操作手册；执行层本体是 `src/openinvest/jobs/paper_autopilot.py`
（`autopilot.enabled` 默认关，**只应在独立的 INVEST_HOME 里开**）。

一句话：开启后，这个 INVEST_HOME 里的每条 ACCUMULATE / BUY / TRIM / SELL 裁决都会在当天收盘价上自动记账成交；
HOLD 不动；裁决规则本身一字不改。它不下真单、不碰真实账户。

## 同起点原则

`clone_home.py` 只复制 `memory/user.md` / `strategy.md` / `portfolio.md`（同样的持仓、同样的现金），
**不复制** `.committee/ .dreams/ .state/ .backtest*/ trades.db`、`portfolio_history.jsonl` 等任何历史——新账户的账本从零开始。
`portfolio.md` 里每条 holding 的 `channel` 改成 `paper_autopilot`，旧幂等键表一并丢掉；另写 `memory/.autopilot_origin.json`
（`cloned_at`、`src_total_cny`）。拒绝覆盖已存在且非空的 dst。脚本不含任何数据，只复制你自己机器上的文件。

```bash
cd <invest checkout>
uv run python experiments/paper_autopilot/clone_home.py --src <生产 INVEST_HOME> --dst <新 INVEST_HOME>
# 想要「买入持有」对照：再克隆一份，不开 autopilot、不挂 cron
uv run python experiments/paper_autopilot/clone_home.py --src <生产 INVEST_HOME> --dst <冻结克隆 INVEST_HOME>
```

## 每日流程

`openinvest autopilot_daily`（给没有 scheduler 的 INVEST_HOME 用 cron 跑）顺序执行：

1. `daily_report`（**不发邮件**）——同一套委员会出当日裁决，落到 `memory/.committee/<今天>/`；
2. `paper_autopilot`——读当日还没有 execution 记录的裁决，按下表在本地账本成交，并 `record_execution`；
3. `verdict_review`——复盘（只读行情库）。

三段各自隔离失败；输出 JSON；任一段抛异常则退出码 1。第 2 步在 `autopilot.enabled=false` 时是 no-op。

## 成交规则

| 裁决 | 行为 |
|---|---|
| HOLD / UNCLEAR / 无 alloc | 不动、不记 execution（和人一样「没事做」） |
| ACCUMULATE / BUY | 金额 = `|alloc_cny|`（CIO 已被 Sanity6 钳到用户上限，不二次钳）；价 = 当日首个缓存 bar（通常为收盘价；若同一 home 盘中跑过 scheduler / 哨兵，可能是更早缓存的盘中价）；数量 = floor(金额 ÷ 价 ÷ 手) × 手 |
| TRIM | 卖出 `|alloc_cny|` 等值（整手、≤ 持有量） |
| SELL | 全部卖出（不受最小单限制） |
| 场外基金（`FUND:` 开头，T+1 两段式） | 不成交，记 `executed=false, reason=paper_autopilot:unsupported_otc_fund` |

- **必须有今天的 bar**：行情源没拉到 → `skip(stale_quote)`；最新 bar 不是今天（休市）→ `skip(market_closed)`；两者都不动账本、不占幂等闸，当日可重跑。按北京日期比 bar，
  所以美股 / 欧股（北京 16:35 还没开盘）不受支持，会 `market_closed`。黄金 proxy 不带 bar 日期，照旧成交。
- **手数**：`.SS/.SZ` 100、`.HK` 固定 100（真实港股每手因股而异，如 2800.HK 是 500 股；账本不会出错，但与「人执行」的可比性有偏差）、`.AX` 1、金属 / 加密可小数（保留 4 位）。
- **币种 / 单位**：有持仓取持仓的 `cost_currency / unit_label / proxy_kind`；没有持仓的标的按后缀猜币种；黄金 GC=F 走 CNY/克。
- **最小单**：金额 < `autopilot.min_order_cny`（默认 500）或取整后 0 股 → `skip(too_small)`。
- **现金**：按币种扣。该币种现金不够，从 CNY 按当日汇率换汇（`withdraw` CNY + `deposit` 目标币，note 为 `paper fx`），CNY 也不够就缩量到整手，缩到 0 → `skip(no_cash)`。现金永不为负。
- **手续费**：成交额 × `autopilot.commission_bps / 1e4`（默认 3bp），用 ADR-027 的 `fee` 活动另记一行。
- 终局性跳过（`too_small / no_cash / no_position`）会记 `executed=false, reason=paper_autopilot:<原因>`，`decisions` 里能看到「程序也没成交」及原因。
- 持仓币种与报价币种不一致 → `currency_mismatch`；换汇后买入失败会反向换回并记 `buy_failed`；`duplicate_key`（账本幂等键拦下，说明这笔其实已成交）不写 execution 声明。
- 同日多条裁决：先卖后买（卖出回款可供当天买入），其余按 symbol 字母序，保证确定性。

幂等（ADR-016）：每个 `(日期, symbol, side)` 一把 `state_claim`；`buy / sell / fee / fx` 各带 `idempotency_key`；账本一旦提交就不再 unclaim。

## 费用

只有委员会花 token：模拟账户跑 4 个标的、模型 Sonnet，约 **¥2.7/天**（估算，上线后以 `memory/.state/llm_usage.jsonl` 为准）。执行层本身零 LLM、零联网（行情走缓存/行情库）。

## 怎么开

```bash
INVEST_HOME=<dst> uv run openinvest config --set autopilot.enabled true        # 或设 env INVEST_AUTOPILOT_ENABLED=true
INVEST_HOME=<dst> uv run openinvest config --set autopilot.commission_bps 3    # 可选
INVEST_HOME=<dst> uv run openinvest config --set autopilot.min_order_cny 500   # 可选
```

配置落在 `<dst>/memory/.state/config_overrides.json`，不影响生产 hub。

## cron 示例

LLM 环境变量从生产 `.env` 取（不写明文；`.env` 里不带引号时才对，key 不会进日志）。**合并并等生产 checkout 自动 pull 之后再挂**（旧代码不认 `autopilot_daily`）。

```
30 16 * * 1-5 export PATH="$HOME/.local/bin:$PATH"; cd /home/ubuntu/projects-review/invest && INVEST_HOME=<dst> LLM_API_KEY="$(grep -E '^LLM_API_KEY=' .env | cut -d= -f2-)" LLM_BASE_URL="$(grep -E '^LLM_BASE_URL=' .env | cut -d= -f2-)" LLM_MODEL="$(grep -E '^LLM_MODEL=' .env | cut -d= -f2-)" uv run openinvest autopilot_daily >> <dst>/memory/autopilot.log 2>&1
```

委员会要几分钟，整条流水线 16:30 起跑，成交在日报之后顺序发生，此时 A 股（15:00）、港股（16:00）、澳股都已收盘。
（scheduler 里的 `paper_autopilot.yml` 排在 16:35，只给带 scheduler 的 home 用；默认 no-op。）

## 怎么比较

三个 INVEST_HOME 各看一次：

| 账户 | 命令 |
|---|---|
| 真实（人执行） | `INVEST_HOME=<真实> uv run openinvest performance` |
| autopilot（程序执行） | `INVEST_HOME=<dst> uv run openinvest performance` |
| 冻结克隆（买入持有） | `INVEST_HOME=<冻结克隆> uv run openinvest status` 的总资产，对比 `.autopilot_origin.json` 的 `src_total_cny`（它不跑任何 job，净值 = 起点持仓按今日价重估） |

采纳情况：`INVEST_HOME=<dst> uv run openinvest decisions` 里每条方向性裁决都有 `execution`（`paper_autopilot` 成交或带原因的未成交）。
