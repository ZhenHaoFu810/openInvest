# paper_fleet — 每日前瞻纸面委员会(方案二,ADR-022 更新节)

**目的**:持续生产**不受模型升级影响**的干净样本。决策时未来尚不存在 ⇒ 任何未来
模型都无记忆可穿越(2026-07 deepseek-v4-flash cutoff 事件实证:历史回填桶是相对
模型的,前瞻样本是唯一免疫源)。

⚠️ **评分口径**:`jobs/verdict_review` 每天 02:00 只把 live 写进 `verdict_review.jsonl`;舰队样本(本目录前瞻部分)每天另打一遍 30d 标签,**只进**裁决旁的同类决议查表 `.dreams/confidence_lookup.json`(每格记 n_live / n_fleet),不进命中率页和纪律台账。舰队进 jsonl 的全量重建仍是手动`uv run python -m openinvest.jobs.verdict_review --include-backtest`(纯本地计算,零 API 费用)。

## 形态(2026-07-24 重设计,v1 的独立 INVEST_HOME 方案已退役)

- **就在原仓库跑,用原有 .env**,零新增配置、零新组件
- 决策写 `memory/.backtest/<今天>/`——与真实 `.committee/` 账本天然隔离,
  gitignore 已覆盖,夜间 restic 备份自动带上
- 上下文完整:事件账本、dreaming insights 全在(独立空目录的"失忆委员会"问题不存在)
- 组合画像走 backtest 既有的中性硬编码(ADR-022 §6):真实持仓不会混进纸面决策,
  代价是 verdict 分布缺集中度维度,不可外推 live
- 入口:`scripts/backtest_committee.py --prospective`(只跑今天,周末自动跳过,
  与回填参数互斥;Contaminated 章恒为 false)

## 运行

```bash
# 手动跑一天(50 标的 ≈ 2 分钟 @ BACKTEST_WORKERS=25,按 2026-07 实测价 ≈ ¥0.1)
SYMS=$(uv run python -c "import yaml; print(','.join(yaml.safe_load(open('experiments/paper_fleet/universe.yml'))['symbols']))")
BACKTEST_WORKERS=25 uv run python -m scripts.backtest_committee --prospective --assets "$SYMS"
```

crontab(北京 06:30,美盘收盘后;已于 2026-07-24 挂上,07-25 修 PATH——
cron 的 /bin/sh 不含 ~/.local/bin,首夜因 `uv: not found` 空跑一次):

```
30 22 * * * export PATH="$HOME/.local/bin:$PATH"; cd /home/ubuntu/projects-review/invest && BACKTEST_WORKERS=25 uv run python -m scripts.backtest_committee --prospective --assets "$(uv run python -c "import yaml; print(','.join(yaml.safe_load(open('experiments/paper_fleet/universe.yml'))['symbols']))")" >> memory/.backtest/fleet_daily.log 2>&1
```

## 试跑臂：T2 CONFIDENCE 定义(D11 P2,2026-10)

`--prospective --t2-confidence-arm`:对照臂(上面那份,写 `memory/.backtest/`)跑完后,
同一批新鲜标的再跑一整轮委员会,只有 CIO prompt 不同——删掉"三方一致 confidence ≥ 0.85"
数字规则,加上 CONFIDENCE 定义("30 个日历天后被 verdict_review 判为命中的概率";HOLD
命中 = 30 天涨跌留在该资产正常波动带内)。T2 臂写 `memory/.backtest_t2conf/<今天>/`,
verdict_review / dreaming / #141 样本计数都只读 `.backtest`,碰不到它。成本 ×2(≈ ¥3/月 → ¥6/月)。

- 变体在 `scripts/backtest_committee.py:build_cio_prompt_t2`;live 委员会不 import 本脚本,
  live CIO prompt 逐字节不变(`tests/test_fleet_confidence_t2.py`)
- cio.md 改了那两处锚点措辞 → T2 臂在花 LLM 钱前直接报错退出(对照臂照常落盘),要同步改变体
- 开 / 停:在上面 crontab 那行 `--prospective` 后加 / 删 `--t2-confidence-arm`
- 判读口径(臂、指标、护栏、停止规则)按私有归档里的预注册,不在本 repo

## 试跑臂：B4 三臂（sealed / debate / macro-soft，评审路线 B4 + #461，2026-10）

三个独立的 flag，都只能和 `--prospective` 同用；对照臂（上面那份）和 T2 臂跑完后，同一批新鲜标的、**同一份输入**
（同 market_data / regime / 中性持仓；macro_view 借对照臂这次跑出来的那份，对照臂当天已整天跑完被续跑跳过时才自己跑一次）各再跑一臂，
每臂只比对照臂多一个变量：

| flag | 目录 | 比对照多的那个变量 |
|---|---|---|
| `--sealed-arm [--sealed-n 3]` | `memory/.backtest_sealed/<今天>/` | 每标的独立采样 N 次 rounds=1，按严格多数聚合（三者各异 → HOLD 并标 split；confidence=最大票占比；alloc=多数票中位数） |
| `--debate-arm` | `memory/.backtest_debate/<今天>/` | rounds=4 单次抽样（= live 日报配置） |
| `--macro-soft-arm` | `memory/.backtest_macrosoft/<今天>/` | CIO 规则 2 换成“Macro risk_off 且 STRENGTH<8 时不否决、金额 ×(10−STRENGTH)/10”（#461；运行期 patch，live prompt 不变；锚点失效 → 只跳过这一臂） |

落盘：Input Health 多 `arm` 标签（`sealed_n3` / `debate_r4` / `macrosoft_r1`）、`macro_signal` / `macro_strength` / `macro_shared`（这行的 macro 是否确是对照臂同日同标的那份，不是的复盘时剔掉），sealed 另有 `votes` / `flip` / `split`，
debate 另有 `final_round` / `converged`；同日已落盘的标的跳过（断点续跑）；sealed 臂任一次抽样失败 → 该标的不落盘。对照臂、T2 臂的决策内容、live 裁决一个字节都不变（对照臂 / T2 臂的 Input Health 自 2026-10-18 起多一个 `model` 键，复盘 model_era 据此认模型；更早的行没有，记 `direct:unknown`）
（`tests/test_sealed_arm.py` 守）。

- 复盘：`verdict_review` 每日 job 尾巴调 `run_arms()`，每臂写独立的 `memory/.dreams/verdict_review_<臂>.jsonl`，加一份
  `docs/verdict_accuracy_arms.md`（均不入库），**不进** live 命中率页 / 公开 JSON / confidence_lookup(`tests/test_arm_review.py` 守)
- 实验设计、成本(三臂合计 ≈ +¥27/月)、判据(H1–H3,判读 +65 天)、局限 → [`experiments/sealed_vote/README.md`](../sealed_vote/README.md)
- **开 / 停**:在 crontab 那行 `--prospective` 后加 / 删对应 flag。**合并并等生产 checkout 自动 pull 之后再改 crontab**
  (旧代码不认这些 flag,argparse 报错会让整条舰队 cron 失败)。三臂全开的行:

```
30 22 * * * export PATH="$HOME/.local/bin:$PATH"; cd /home/ubuntu/projects-review/invest && BACKTEST_WORKERS=25 uv run python -m scripts.backtest_committee --prospective --t2-confidence-arm --sealed-arm --debate-arm --macro-soft-arm --assets "$(uv run python -c "import yaml; print(','.join(yaml.safe_load(open('experiments/paper_fleet/universe.yml'))['symbols']))")" >> memory/.backtest/fleet_daily.log 2>&1
```

- 开任一试跑臂时 `INVEST_MAX_DEBATE_ROUNDS` 必须未设或为 1，否则直接退出（花钱前）——对照 / macro-soft 臂读它，sealed / debate 臂固定轮数
- 实验开跑后别改 `--sealed-n`(同一目录混不同 N 的行不可比;复盘报告会按 `arm` 标签分开计数提示)
- 墙钟:sealed 与 debate 臂各约为对照臂的 3 倍(标的间并发不变,同标的的抽样 / 辩论轮次串行)
- 备份:`jobs/backup.py` 的 `.backtest*` 前缀规则自动覆盖三个新目录(周日全量带上)

## 模型臂：Sonnet（`--sonnet-arm`，2026-10 换模型 #483 之后）

舰队其余臂（对照 / T2 / sealed / debate / macro-soft）**继续钉 DeepSeek**——它们回答“结构”问题（投票 / 辩论 / macro-soft 有没有用），判读日 2026-12-22 不变。
但生产委员会已换成 Sonnet 5.5，舰队里没有 Sonnet 就看不出“换模型本身”的效应，live 每天只有 ~4 条裁决，Sonnet 期的样本要等很久。
`--prospective --sonnet-arm`：**同一批标的、同一套 live 配置（rounds=1、单次抽样 = 对照臂）只把 LLM 换成 Sonnet**，写 `memory/.backtest_sonnet/<今天>/`（每天 ≈ 50 条）。

- **LLM 覆盖**：模型 / 端点 / key 的环境变量名来自 config `fleet.sonnet_arm`（`core/config/tunable.py:FleetConfig`；默认
  `claude-sonnet-5-5` / `https://api.anthropic.com/v1` / `FLEET_SONNET_API_KEY`；key 值**不进配置**，只存变量名）。
  运行期 patch `utils.llm.get_llm_config` / `get_llm_config_safe`，**只在该臂的 `with` 作用域内**，退出（含异常）即还原
  （同 T2 臂；`tests/test_sonnet_arm.py` 守：作用域内新建 agent 走 Sonnet、之外仍是 DeepSeek）。
- **Macro 不共享**：这一臂的 Macro 视图由 Sonnet 自己生成（“换模型”的一部分），不借对照臂的。所以 Input Health 的 `macro_shared` 恒为 `false`——
  复盘**不因此剔行**（其余臂会剔），改在 `docs/verdict_accuracy_arms.md` 单列「模型对照」一节，与对照臂同日同标的配对比较
  （30d 命中 / 提升 / 超额 / HOLD 占比 / 逐日方向翻转 / 照做净收益率）。差异 = Macro + Quant + Risk + CIO **整条流水线**一起换模型的总效应，拆不到某个角色。
  稳定度那组（逐票翻转 / 一致率 / 无多数）对它**不适用**（单次抽样，1 票），报告里标 n/a。
- **落盘**：Input Health `arm: "sonnet_live_cfg"`、`model` 是真实调用时的模型名（`claude-sonnet-5-5`）、`macro_signal` / `macro_strength` / `final_round` / `converged`。
  复盘 `model_era` = `direct:claude-sonnet-5-5`，报告臂一览里单列模型。
- **缺 key**：`FLEET_SONNET_API_KEY` 没设（或全空白）→ 这一臂在花钱前跳过，打印原因，**退出码非 0**（其余臂照跑、照落盘）。
- **预检**：进臂先花 1 个 token 调一次该模型（`_sonnet_preflight`，用的就是本臂 patch 后的 key / 端点 / 模型名）；401 / 404 等一律按缺 key 处理（跳过、退出码非 0）。不预检的话坏 key 会让四个角色全记 `[WORKER_UNAVAILABLE]`、CIO 压成 HOLD，50 行照样按“成功”落盘。
- 不设通过门槛：这是描述性对照（“换了模型之后，同一批输入上裁决差多少”），不是 H1–H3 那样的预注册检验；若要冻结判据另签。
- 只能和 `--prospective` 同用；开任一试跑臂时 `INVEST_MAX_DEBATE_ROUNDS` 必须未设或为 1（同其余臂）。

**成本**（`llm_usage.jsonl` 里 Sonnet 的实测 token × `llm_telemetry` 牌价 ¥14 / ¥70 每百万 token；Anthropic 的 OpenAI 兼容层不支持 prompt caching，所以只有未命中价）。
3 个标的 + 1 次共享 Macro 的实测：

| 角色 | 调用 | 输入 token | 输出 token | ¥ |
|---|---|---|---|---|
| Macro（全舰队每天 1 次） | 2 | 6,993 | 643 | 0.143 |
| Quant | 3 | 9,145 | 1,961 | 0.265 |
| Risk | 3 | 4,812 | 1,250 | 0.155 |
| CIO | 3 | 19,051 | 7,568 | 0.796 |
| 合计 | 11 | 40,001 | 11,422 | **1.359** |

= 每标的 ≈ **¥0.405**（CIO 最贵：输出长，占 ~59%）+ 每天 1 次 Macro ¥0.143。舰队 50 标的的工作日 ≈ 50 × 0.405 + 0.143 ≈ **¥20.4/天**；
周末只有加密（3 个）开市 ≈ ¥1.4/天；折合约 **¥455/月**（21.7 个工作日 + 8.7 个周末日）。DeepSeek 同样三个标的 ≈ ¥0.016，贵约 85 倍。
这是 3 个加密标的的实测，股票 / 商品标的的 CIO 输出长度可能不同，上线后用 `memory/.state/llm_usage.jsonl` 按 `model=claude-sonnet-5-5` 汇总核对第一周的真实日均。

**开 / 停**：在 crontab 那行 `--prospective` 后加 / 删 `--sonnet-arm`。**合并并等生产 checkout 自动 pull 之后再改 crontab**（旧代码不认这个 flag，argparse 报错会让整条舰队 cron 失败）。
需要在 cron 里设 `FLEET_SONNET_API_KEY`（值取 `.env` 的 `LLM_API_KEY`，不要把 key 写进仓库 / crontab 明文），并保持其余 `LLM_*` 清空，让其他臂仍走 DeepSeek。完整一行（四臂 + Sonnet 臂）：

```
30 22 * * * export PATH="$HOME/.local/bin:$PATH"; cd /home/ubuntu/projects-review/invest && FLEET_SONNET_API_KEY="$(grep -E '^LLM_API_KEY=' .env | cut -d= -f2-)" LLM_API_KEY= LLM_BASE_URL= LLM_MODEL= BACKTEST_WORKERS=25 uv run python -m scripts.backtest_committee --prospective --t2-confidence-arm --sealed-arm --debate-arm --macro-soft-arm --sonnet-arm --assets "$(uv run python -c "import yaml; print(','.join(yaml.safe_load(open('experiments/paper_fleet/universe.yml'))['symbols']))")" >> memory/.backtest/fleet_daily.log 2>&1
```

- `$(grep …)` 在 `.env` 里 `LLM_API_KEY=` 不带引号时才对（生产现状）；key 不会进 `fleet_daily.log`。
- `BACKTEST_WORKERS=25` 对 Sonnet 臂也生效：并发 25 路打 Anthropic，撞限流时 `_ask` 会退避重试，重试耗尽的角色记 `[WORKER_UNAVAILABLE]`（复盘「残缺输入上做的裁决」计数会涨）。首周看那个计数，高了就给 Sonnet 臂单独降并发。
- 备份：`jobs/backup.py` 的 `.backtest*` 前缀规则自动覆盖 `.backtest_sonnet/`。

## 标的池

- `universe.yml` — 舰队每日 50 标的(八资产类别)
- `universe_l2/l3/l4.yml` — 历史回填扩层清单(L2 +100 / L3 +240 / L4 +389,
  与舰队共用 MarketStore 缓存;L4 回填于 2026-07-24 按预算暂停,断点续跑随时可续)

## 保护闸(2026-07-24 CR 后加)

- **行情新鲜度**:逐标的检查缓存最新 bar,**不是当日 bar 就跳过**并打印修复命令——决不拿
  陈旧收盘价出当天 verdict(那会让 verdict_review 拿真实后市给错标样本打分)。逐标的判定
  顺带覆盖周末、各市场假日不同步与加密 7×24。
  ⚠️ **2026-07-25 ~ 2026-09-27 的周末目录是污染样本**:当时阈值是"≤5 天",周末用周五
  收盘价各出了两份重复 verdict(22 天 × 50 ≈ 1100 份)。评分/统计时按决策日
  `weekday()>=5` 且非加密标的剔除;2026-10-07 起已改为严格当日。
- **成本闸**:`--limit N` 在 prospective 下有效(只跑前 N 个标的);`--step` 等回填
  参数一律拒绝而非静默忽略。
- **失败可见**:结尾打印 `ok/total`,有失败则 exit 1,cron 日志不会静默成功。
- **币种**:按 yfinance 后缀映射(.HK→HKD/.T→JPY/.SS→CNY/裸 ticker→USD),
  取代原先"非 NDQ.AX 一律 CNY"的硬编码。

## 产出口径

50 条/交易日 ≈ 每年 ~12,600 条永久干净样本,成本 ≈ ¥3/月。累计样本随
`jobs/verdict_review` 评分后进入 `memory/.dreams/verdict_review.jsonl`,与回填
语料同一账本、同一分桶纪律(cutoff 单一可信源 `review_calc.CONTAMINATION_CUTOFF`)。
